from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.db import Database, utc_now
from app.intelligence import ANALYSIS_PROMPT_VERSION
from app.logging_runtime import RuntimeLog
from app.main import create_app
from app.pipeline import IntelligencePipeline
from test_intelligence_pipeline import FakeDeepSeek

ROOT = Path(__file__).resolve().parents[3]


class CaptureFake(FakeDeepSeek):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def complete_json(self, *, operation, system, user):
        self.requests.append({"operation": operation, "system": system, "user": user})
        result = await super().complete_json(operation=operation, system=system, user=user)
        if operation == "post_analysis":
            result.update({
                "category": "other", "codex_relevant": False, "temporal_mode": "unclear",
                "explicit_announcement": False, "event_status": "none", "event_type": "NONE",
                "special_type": None, "canonical_eligible": False, "scope": "unknown",
                "execution_stage": "unknown", "event_time_start": None, "event_time_end": None,
                "time_basis": "unknown", "evidence_quote": "", "summary": "Offline context fixture.",
                "event_title": "", "effects": [], "context_sufficient": True,
            })
        return result


class SourceJudge:
    model = "offline-source-judge"

    def __init__(self, source_id, on_request=None):
        self.source_id = source_id
        self.on_request = on_request
        self.requests = []

    async def complete_json(self, *, operation, system, user):
        self.requests.append({"operation": operation, "system": system, "user": user})
        if operation != "radar_judge":
            raise AssertionError(f"unexpected operation {operation}")
        if self.on_request:
            self.on_request()
        return {
            "action_level": "GREEN", "horizon_24h": "GREEN", "horizon_48h": "YELLOW",
            "horizon_72h": "ORANGE", "estimated_start": None, "estimated_end": None,
            "estimate_basis": "Offline contract fixture; no time prediction.",
            "reason_summary": "Offline source-version contract fixture.",
            "evidence_post_ids": [self.source_id],
        }


class CitationFake(CaptureFake):
    def __init__(self, evidence_post_ids, *, on_judge=None):
        super().__init__()
        self.evidence_post_ids = [str(value) for value in evidence_post_ids]
        self.on_judge = on_judge

    async def complete_json(self, *, operation, system, user):
        result = await super().complete_json(operation=operation, system=system, user=user)
        if operation == "radar_judge":
            if self.on_judge:
                self.on_judge()
            result["evidence_post_ids"] = self.evidence_post_ids
        return result


def _request_json(request):
    return json.loads(request["user"].splitlines()[-1])


def _pipeline(db, model, tmp_path):
    return IntelligencePipeline(
        database=db,
        client=model,
        runtime_log=RuntimeLog(tmp_path / "logs", 5, 1_048_576),
        collector_state={},
        repository_root=ROOT,
    )


def _api_snapshot(db, settings, tmp_path):
    api_settings = replace(
        settings, database_path=db.path, log_dir=tmp_path / "api-logs", deepseek_api_key=""
    )
    with TestClient(create_app(api_settings)) as client:
        for component in ("profile_monitor", "replies_monitor", "search_backfill"):
            client.post("/api/v2/collector/heartbeat", json={
                "component": component, "instance_id": f"{component}-fixture", "sequence": 1,
            })
        return client.get("/api/v2/radar").json()


def _context_node(tweet_id, author, text, posted_at, parent_id=None):
    return {
        "tweet_id": tweet_id,
        "author": author,
        "text": text,
        "posted_at": posted_at,
        "parent_id": parent_id,
        "relation_source": "x_replied_to_field",
        "language": "en",
        "completeness": "complete",
    }


def _seed_unanalysed_tibo_parent_chain(db):
    now = datetime.now(UTC)
    ancestor_id, parent_id, reply_id = (
        "990000000000000101", "990000000000000102", "990000000000000103"
    )
    ancestor_at = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    parent_at = (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
    reply_at = (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
    records = [
        {"tweet_id": ancestor_id, "text": "Original quota plan.", "posted_at": ancestor_at,
         "collected_at": utc_now(), "source": "offline_fixture"},
        {"tweet_id": parent_id, "text": "The reset will land within two hours.", "posted_at": parent_at,
         "collected_at": utc_now(), "is_reply": True, "reply_to_tweet_id": ancestor_id,
         "source": "offline_fixture"},
        {"tweet_id": reply_id, "text": "The timing is confirmed.", "posted_at": reply_at,
         "collected_at": utc_now(), "is_reply": True, "reply_to_tweet_id": parent_id,
         "source": "offline_fixture"},
    ]
    inserted = db.upsert_posts_detailed(records)
    observed_at = utc_now()
    for tweet_id, text, posted_at, direct_parent in (
        (ancestor_id, "Original quota plan.", ancestor_at, None),
        (parent_id, "The reset will land within two hours.", parent_at, ancestor_id),
        (reply_id, "The timing is confirmed.", reply_at, parent_id),
    ):
        db.contexts.record_observation(
            _context_node(tweet_id, "thsottiaux", text, posted_at, direct_parent), observed_at
        )
    return {
        "ancestor_id": ancestor_id,
        "parent_id": parent_id,
        "reply_id": reply_id,
        "reply_post_id": next(item["post_id"] for item in inserted if item["tweet_id"] == reply_id),
    }


def test_reply_context_reaches_product_analysis_judge_and_api(tmp_path, settings):
    db = Database(tmp_path / "reply-context.db")
    db.initialize()
    now = datetime.now(UTC)
    parent_at = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    reply_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    parent_id, reply_id = "990000000000000006", "990000000000000007"
    inserted = db.upsert_posts_detailed([{
        "tweet_id": reply_id,
        "text": "Thanks for clarifying the release window.",
        "posted_at": reply_at,
        "collected_at": utc_now(),
        "is_reply": True,
        "reply_to_tweet_id": parent_id,
        "source": "offline_fixture",
    }])[0]
    observed_at = utc_now()
    db.contexts.record_observation(
        _context_node(parent_id, "community_member", "What is the release window?", parent_at),
        observed_at,
    )
    db.contexts.record_observation(
        _context_node(reply_id, "thsottiaux", "Thanks for clarifying the release window.", reply_at, parent_id),
        observed_at,
    )

    model = CaptureFake()
    pipeline = _pipeline(db, model, tmp_path)

    async def run_product_path():
        await pipeline._process_post(inserted["post_id"])
        as_of = utc_now()
        judgement_id = await pipeline.run_judge(as_of=as_of, data_health="HEALTHY")
        return as_of, judgement_id

    as_of, judgement_id = asyncio.run(run_product_path())
    judgement = db.latest_judgement(as_of=as_of)
    assert judgement is not None and judgement["id"] == judgement_id
    assert db.validate_judgement(judgement, at=as_of)["reason"] == "VALID"

    analysis_request = next(req for req in model.requests if req["operation"] == "post_analysis")
    analysis_post = _request_json(analysis_request)["post"]
    assert analysis_post["author"] == "thsottiaux"
    assert analysis_post["reply_context"]["nodes"][0]["author"] == "community_member"
    assert analysis_post["reply_context"]["nodes"][0]["tweet_id"] == parent_id

    judge_request = next(req for req in model.requests if req["operation"] == "radar_judge")
    judge_context = _request_json(judge_request)["context"]
    judged_reply = next(post for post in judge_context["posts"] if post["tweet_id"] == reply_id)
    assert judged_reply["author"] == "thsottiaux"
    assert judged_reply["reply_context"]["nodes"][0]["author"] == "community_member"
    assert judged_reply["reply_context"]["nodes"][0]["text"] == "What is the release window?"
    assert judgement["raw"]["input_versions"][reply_id] == judged_reply["input_hash"]
    assert judgement["raw"]["input_snapshot_id"]
    assert db.get_post_by_tweet_id(parent_id) is None
    assert all(parent_id not in event["evidence_post_ids"] for event in db.list_reset_events())

    api = _api_snapshot(db, settings, tmp_path)
    assert api["validation"]["reason"] == "VALID"
    assert api["judgement_id"] == judgement_id
    assert api["action_level"] == judgement["action_level"]


def test_judge_snapshot_closes_over_exposed_unanalysed_tibo_parent_and_ancestor(tmp_path, settings):
    db = Database(tmp_path / "exposed-parent-version.db")
    db.initialize()
    ids = _seed_unanalysed_tibo_parent_chain(db)
    model = CitationFake([ids["parent_id"]])
    pipeline = _pipeline(db, model, tmp_path)

    async def run_product_path():
        await pipeline._process_post(ids["reply_post_id"])
        as_of = utc_now()
        judgement_id = await pipeline.run_judge(as_of=as_of, data_health="HEALTHY")
        return as_of, judgement_id

    as_of, judgement_id = asyncio.run(run_product_path())
    stored = db.latest_judgement(as_of=as_of)
    validation = db.validate_judgement(stored, at=as_of)
    api = _api_snapshot(db, settings, tmp_path)
    request = next(req for req in model.requests if req["operation"] == "radar_judge")
    request_context = _request_json(request)["context"]
    judged_reply = next(post for post in request_context["posts"] if post["tweet_id"] == ids["reply_id"])
    exposed = judged_reply["reply_context"]["nodes"]

    assert {ids["parent_id"], ids["ancestor_id"]}.isdisjoint(
        {post["tweet_id"] for post in request_context["posts"]}
    )
    assert [node["tweet_id"] for node in exposed] == [ids["parent_id"], ids["ancestor_id"]]
    assert all(node["author"] == "thsottiaux" for node in exposed)
    assert all(node["text"] == db.get_post_by_tweet_id(node["tweet_id"])["original_text"] for node in exposed)
    assert all(node["canonical_post_id"] == db.get_post_by_tweet_id(node["tweet_id"])["id"] for node in exposed)
    assert all(db.get_post_by_tweet_id(node["tweet_id"])["analysis"] is None for node in exposed)
    assert ids["parent_id"] in stored["raw"]["input_versions"], (
        f"validation={validation}; radar={api}; stored_versions={sorted(stored['raw']['input_versions'])}"
    )
    assert ids["ancestor_id"] in stored["raw"]["input_versions"]
    assert stored["raw"]["input_versions"][ids["parent_id"]] == db._post_input_version(ids["parent_id"], as_of=as_of)
    assert stored["raw"]["input_versions"][ids["ancestor_id"]] == db._post_input_version(ids["ancestor_id"], as_of=as_of)
    assert stored["id"] == judgement_id
    assert validation["reason"] == "VALID"
    assert api["validation"]["reason"] == "VALID"
    assert api["judgement_id"] == judgement_id
    assert api["action_level"] == stored["action_level"]


def test_judge_does_not_persist_citation_to_existing_unexposed_post(tmp_path, settings):
    db = Database(tmp_path / "unexposed-citation.db")
    db.initialize()
    ids = _seed_unanalysed_tibo_parent_chain(db)
    outsider_id = "990000000000000199"
    db.upsert_posts_detailed([{
        "tweet_id": outsider_id, "text": "Known but not exposed to this Judge call.",
        "posted_at": utc_now(), "collected_at": utc_now(), "source": "offline_fixture",
    }])
    model = CitationFake([outsider_id])
    pipeline = _pipeline(db, model, tmp_path)

    async def run_product_path():
        await pipeline._process_post(ids["reply_post_id"])
        as_of = utc_now()
        caught = None
        try:
            await pipeline.run_judge(as_of=as_of, data_health="HEALTHY")
        except ValueError as error:
            caught = str(error)
        stored = db.latest_judgement(as_of=as_of)
        api = _api_snapshot(db, settings, tmp_path)
        return caught, stored, api

    caught, stored, api = asyncio.run(run_product_path())
    request = next(req for req in model.requests if req["operation"] == "radar_judge")
    request_context = _request_json(request)["context"]
    exposed_ids = {post["tweet_id"] for post in request_context["posts"]}
    exposed_ids.update(node["tweet_id"] for post in request_context["posts"]
                       for node in post.get("reply_context", {}).get("nodes", []))

    assert outsider_id not in exposed_ids
    assert caught and "MISSING_INPUT_VERSION" in caught, f"stored={stored}; radar={api}; error={caught}"
    assert stored is None
    assert api["judgement_id"] is None
    assert api["action_level"] == "UNKNOWN"
    assert api["display_mode"] == "unavailable"


def test_judge_does_not_close_over_previous_judgement_id_without_exposed_body(tmp_path):
    db = Database(tmp_path / "history-only-citation.db")
    db.initialize()
    ids = _seed_unanalysed_tibo_parent_chain(db)
    history_id = "990000000000000198"
    db.upsert_posts_detailed([{
        "tweet_id": history_id, "text": "Body is not included in the prior result.",
        "posted_at": utc_now(), "collected_at": utc_now(), "source": "offline_fixture",
    }])
    prior_created = utc_now()
    prior_version = db._post_input_version(history_id)
    prior_id = db.add_judgement({
        "created_at": prior_created, "valid_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "action_level": "GREEN", "horizon_24h": "GREEN", "horizon_48h": "YELLOW",
        "horizon_72h": "ORANGE", "data_health": "HEALTHY", "reason_summary": "Prior fixture.",
        "evidence_post_ids": [history_id], "status": "COMPLETED",
        "raw": {"input_versions": {history_id: prior_version}},
    })
    model = CitationFake([history_id])
    pipeline = _pipeline(db, model, tmp_path)

    async def run_product_path():
        await pipeline._process_post(ids["reply_post_id"])
        as_of = utc_now()
        with pytest.raises(ValueError, match="MISSING_INPUT_VERSION"):
            await pipeline.run_judge(as_of=as_of, data_health="HEALTHY")
        return as_of

    as_of = asyncio.run(run_product_path())
    stored = db.latest_judgement(as_of=as_of)
    request = next(req for req in model.requests if req["operation"] == "radar_judge")
    model_context = _request_json(request)["context"]
    exposed_ids = {post["tweet_id"] for post in model_context["posts"]}
    exposed_ids.update(node["tweet_id"] for post in model_context["posts"]
                       for node in post.get("reply_context", {}).get("nodes", []))

    assert model_context["previous_judgement"]["evidence_post_ids"] == [history_id]
    assert history_id not in exposed_ids
    assert stored["id"] == prior_id
    assert db.counts()["radar_judgements"] == 1
    assert db.validate_judgement(stored, at=as_of)["reason"] == "VALID"


def test_judge_rejects_exposed_parent_without_canonical_version_at_as_of(tmp_path):
    db = Database(tmp_path / "unavailable-parent-version.db")
    db.initialize()
    ids = _seed_unanalysed_tibo_parent_chain(db)
    pipeline = _pipeline(db, CitationFake([ids["parent_id"]]), tmp_path)

    async def run_product_path():
        await pipeline._process_post(ids["reply_post_id"])
        as_of = utc_now()
        parent = db.get_post_by_tweet_id(ids["parent_id"])
        db.upsert_posts_detailed([{
            "tweet_id": ids["parent_id"], "text": "Later edited parent body.",
            "posted_at": parent["posted_at"], "source": "offline_fixture",
        }])
        with db.connect() as connection:
            connection.execute("UPDATE tibo_posts SET updated_at=? WHERE id=?",
                               ((datetime.fromisoformat(as_of.replace("Z", "+00:00")) + timedelta(seconds=1)).isoformat(), parent["id"]))
        with pytest.raises(ValueError, match="MISSING_INPUT_VERSION"):
            await pipeline.run_judge(as_of=as_of, data_health="HEALTHY")
        return as_of

    as_of = asyncio.run(run_product_path())
    request = next(req for req in pipeline.client.requests if req["operation"] == "radar_judge")
    request_context = _request_json(request)["context"]
    judged_reply = next(post for post in request_context["posts"] if post["tweet_id"] == ids["reply_id"])

    assert judged_reply["reply_context"]["nodes"][0]["text"] == "The reset will land within two hours."
    assert db._post_input_version(ids["parent_id"], as_of=as_of) is None
    assert db.latest_judgement(as_of=as_of) is None


def test_parent_history_is_as_of_safe_and_semantic_hash_tracks_real_edits(tmp_path):
    db = Database(tmp_path / "parent-history.db")
    db.initialize()
    parent_id, reply_id = "990000000000000016", "990000000000000017"
    reply_at = "2026-09-25T10:01:00Z"
    inserted = db.upsert_posts_detailed([{
        "tweet_id": reply_id, "text": "A short reply.", "posted_at": reply_at,
        "collected_at": "2026-09-25T10:00:00Z", "is_reply": True,
        "reply_to_tweet_id": parent_id, "source": "offline_fixture",
    }])[0]
    reply_post = db.get_post(inserted["post_id"])
    db.contexts.record_observation(
        _context_node(reply_id, "thsottiaux", "A short reply.", reply_at, parent_id),
        "2026-09-25T10:01:00Z",
    )
    db.contexts.record_observation(
        _context_node(parent_id, "community_member", "Old question.", "2026-09-25T10:00:00Z"),
        "2026-09-25T10:00:00Z",
    )

    old_as_of = "2026-09-25T10:02:00Z"
    old_hash = db.contexts.input(reply_post, old_as_of)["input_hash"]
    assert db.contexts.snapshot(reply_post, old_as_of)["nodes"][0]["text"] == "Old question."

    db.contexts.record_observation(
        _context_node(parent_id, "community_member", "Corrected later question.", "2026-09-25T10:00:00Z"),
        "2026-09-25T10:05:00Z",
    )
    assert db.contexts.snapshot(reply_post, old_as_of)["nodes"][0]["text"] == "Old question."
    assert db.contexts.input(reply_post, old_as_of)["input_hash"] == old_hash
    assert db.contexts.input(reply_post)["input_hash"] != old_hash
    assert db.contexts.snapshot(reply_post, "2026-09-25T10:04:00Z")["nodes"][0]["text"] == "Old question."
    assert db.contexts.snapshot(reply_post, "2026-09-25T10:06:00Z")["nodes"][0]["text"] == "Corrected later question."


def test_parent_first_observed_after_as_of_is_not_used_early(tmp_path):
    db = Database(tmp_path / "late-parent.db")
    db.initialize()
    parent_id, reply_id = "990000000000000026", "990000000000000027"
    reply_at = "2026-09-25T10:01:00Z"
    inserted = db.upsert_posts_detailed([{
        "tweet_id": reply_id, "text": "A short reply.", "posted_at": reply_at,
        "collected_at": reply_at, "is_reply": True, "reply_to_tweet_id": parent_id,
        "source": "offline_fixture",
    }])[0]
    reply_post = db.get_post(inserted["post_id"])
    db.contexts.record_observation(
        _context_node(reply_id, "thsottiaux", "A short reply.", reply_at, parent_id), reply_at
    )

    before_parent = "2026-09-25T10:04:00Z"
    assert db.contexts.node(parent_id, as_of=before_parent) is None
    assert db.contexts.snapshot(reply_post, before_parent)["state"] != "READY"

    db.contexts.record_observation(
        _context_node(parent_id, "community_member", "A question arriving later.", "2026-09-25T10:00:00Z"),
        "2026-09-25T10:05:00Z",
    )
    assert db.contexts.node(parent_id, as_of=before_parent) is None
    assert db.contexts.snapshot(reply_post, before_parent)["state"] != "READY"
    after_parent = db.contexts.snapshot(reply_post, "2026-09-25T10:06:00Z")
    assert after_parent["state"] == "READY"
    assert after_parent["nodes"][0]["text"] == "A question arriving later."


def _seed_recent_posts_and_old_event(db, count=30):
    now = datetime.now(UTC)
    source_id = "offline-source-00"
    for index in range(count):
        tweet_id = f"offline-source-{index:02d}"
        posted = (now - timedelta(minutes=count - index)).isoformat().replace("+00:00", "Z")
        result = db.upsert_posts_detailed([{
            "tweet_id": tweet_id, "text": f"Offline source record {index}.", "posted_at": posted,
            "source": "offline_fixture",
        }])[0]
        post = db.get_post(result["post_id"])
        version = db.contexts.input(post)["input_hash"]
        db.save_analysis(result["post_id"], version, "offline-test", ANALYSIS_PROMPT_VERSION, {
            "_input_hash": version, "_text_hash": post["text_hash"], "context_sufficient": True,
            "category": "other", "summary": f"Offline analysis {index}.",
        })
    event = db.upsert_reset_event({
        "event_type": "SPECIAL_RESET", "special_type": "BANKED", "occurred_at": now.isoformat(),
        "source_post_id": db.get_post_by_tweet_id(source_id)["id"], "title": "Offline historical event",
        "summary": "Versioned event summary for an older source post.", "time_basis": "post_time_proxy",
        "scope": "unknown", "execution_stage": "completed", "evidence_post_ids": [source_id],
        "provenance": {"source": "offline_fixture"},
    })
    return now, source_id, event


def test_old_event_source_is_versioned_through_deepseek_pipeline_and_api(tmp_path, settings):
    db = Database(tmp_path / "old-event-source.db")
    db.initialize()
    _, source_id, event = _seed_recent_posts_and_old_event(db)
    context = db.judgement_context()
    assert len(context["posts"]) == 24
    assert source_id not in {post["tweet_id"] for post in context["posts"]}
    assert source_id in context["input_versions"]
    assert context["input_versions"][source_id] == db._post_input_version(source_id)
    assert str(event["id"]) in context["event_versions"]

    model = SourceJudge(source_id)
    pipeline = _pipeline(db, model, tmp_path)
    judgement_id = asyncio.run(pipeline.run_judge(data_health="HEALTHY"))
    judgement = db.latest_judgement()
    assert judgement["id"] == judgement_id
    assert db.validate_judgement(judgement)["reason"] == "VALID"
    request_context = json.loads(model.requests[0]["user"].splitlines()[-1])["context"]
    assert source_id in request_context["reset_events"][0]["evidence_post_ids"]
    assert judgement["raw"]["input_versions"][source_id] == context["input_versions"][source_id]

    api = _api_snapshot(db, settings, tmp_path)
    assert api["validation"]["reason"] == "VALID"
    assert api["judgement_id"] == judgement_id
    assert api["evidence_post_ids"] == [source_id]


def test_input_change_while_judge_is_in_flight_discards_late_result(tmp_path):
    db = Database(tmp_path / "inflight.db")
    db.initialize()
    now, source_id, _ = _seed_recent_posts_and_old_event(db)

    def mutate_source():
        db.upsert_posts_detailed([{
            "tweet_id": source_id,
            "text": "Corrected event source after the request snapshot.",
            "posted_at": now.isoformat().replace("+00:00", "Z"),
            "source": "offline_fixture",
        }])

    pipeline = _pipeline(db, SourceJudge(source_id, on_request=mutate_source), tmp_path)
    with pytest.raises(ValueError, match="input changed while request was in flight"):
        asyncio.run(pipeline.run_judge(data_health="HEALTHY"))
    assert db.latest_judgement() is None
