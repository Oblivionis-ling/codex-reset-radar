from __future__ import annotations

import json

import pytest

from app.corpus_standard import (
    CORPUS_STANDARD_VERSION,
    CorpusValidationError,
    PackageMetadata,
    canonical_posts,
    export_package,
    import_post_records,
    import_review_cases,
    read_jsonl,
    validate_review_result,
)
from app.db import Database


def test_canonical_export_keeps_original_translation_and_string_tweet_id(settings, tmp_path):
    database = Database(settings.database_path)
    database.initialize()
    database.upsert_posts_detailed([{
        "tweet_id": "000123",
        "text": "Resetting tomorrow, not completed yet.",
        "posted_at": "2026-09-01T00:00:00Z",
        "url": "https://x.com/thsottiaux/status/000123",
        "source": "test_fixture",
    }])
    records = canonical_posts(database)
    assert records[0]["tweet_id"] == "000123"
    assert records[0]["content"]["original_text"] == "Resetting tomorrow, not completed yet."
    assert records[0]["content"]["translation_zh"] is None
    assert records[0]["author"]["handle"] == "thsottiaux"

    manifest = export_package(database, tmp_path / "package", PackageMetadata(
        package_id="fixture", frozen_at="2026-09-01T00:00:00Z", generated_at="2026-09-01T00:01:00Z",
        source_database=str(settings.database_path), source_database_sha256="fixture-sha",
        git_head="fixture-head", worktree_fingerprint="fixture-tree", app_version="fixture-version",
        corpus_version=None, model="fixture-model", prompt_versions={"analysis": "a", "translation": "t", "judge": "j"},
        gpt_runtime="fixture-gpt",
    ))
    assert manifest["schema_version"] == CORPUS_STANDARD_VERSION
    assert manifest["files"]["posts.jsonl"]["records"] == 1
    exported = list(read_jsonl(tmp_path / "package" / "posts.jsonl"))
    assert exported[0]["tweet_id"] == "000123"
    assert json.loads((tmp_path / "package" / "manifest.json").read_text(encoding="utf-8"))["package_id"] == "fixture"


def test_review_result_cannot_claim_unreviewed_or_unknown_reviewer():
    base = {
        "schema_version": CORPUS_STANDARD_VERSION,
        "record_type": "review_result",
        "object_stable_id": "post:x:1",
        "review_status": "GPT_REVIEWED",
        "reviewer_kind": "GPT_REFERENCE",
    }
    validate_review_result(base)
    with pytest.raises(CorpusValidationError):
        validate_review_result({**base, "review_status": "UNREVIEWED"})
    with pytest.raises(CorpusValidationError):
        validate_review_result({**base, "reviewer_kind": "DEEPSEEK_SIDE_REVIEWER"})


def test_standard_posts_and_existing_cases_load_without_reference_answers(settings, tmp_path):
    source = Database(tmp_path / "source.db")
    source.initialize()
    post = source.upsert_posts_detailed([{
        "tweet_id": "case-post", "text": "Reset tomorrow.", "posted_at": "2026-09-01T00:00:00Z",
        "source": "test_fixture",
    }])[0]
    source.register_corpus_source({
        "source_id": "fixture-source", "name": "Fixture", "entry_url": "https://example.invalid",
        "accessed_at": "2026-09-01T00:00:00Z", "access_status": "fixture", "acquisition_method": "fixture",
        "provides_tweet_ids": True, "reuse_status": "fixture", "content_kind": "fixture",
    })
    source.upsert_historical_case({
        "case_id": "fixture-case", "tweet_id": "case-post", "source_id": "fixture-source",
        "source_record_key": "fixture:case-post", "posted_at": "2026-09-01T00:00:00Z",
        "original_text": "Reset tomorrow.", "outcome_type": "UNKNOWN", "outcome_at": None,
        "outcome_time_precision": "unknown", "verification_status": "direct_verified",
        "pattern_tags": ["explicit_future"], "related_tweet_ids": [], "corpus_version": "fixture-v1",
    })
    package = tmp_path / "package"
    export_package(source, package, PackageMetadata(
        package_id="fixture", frozen_at="2026-09-01T00:00:00Z", generated_at="2026-09-01T00:01:00Z",
        source_database=str(source.path), source_database_sha256="fixture", git_head="fixture",
        worktree_fingerprint="fixture", app_version="fixture", corpus_version="fixture-v1", model="fixture",
        prompt_versions={}, gpt_runtime="fixture",
    ))

    replay = Database(settings.database_path)
    replay.initialize()
    results = import_post_records(replay, read_jsonl(package / "posts.jsonl"))
    cases = import_review_cases(replay, read_jsonl(package / "review_cases.jsonl"), frozen_at="2026-09-01T00:00:00Z")
    loaded = replay.get_post(results[0]["post_id"])
    assert loaded["analysis_status"] == "PENDING"
    assert loaded["translated_text"] is None
    assert cases == 1
    assert replay.retrieve_historical_cases([], as_of="2026-09-02T00:00:00Z")[0]["case_id"] == "fixture-case"
