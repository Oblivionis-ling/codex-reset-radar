import asyncio
from datetime import UTC, datetime
import json
from dataclasses import replace
from fastapi.testclient import TestClient
from app.main import create_app

import pytest
import httpx
from app.deepseek import DeepSeekClient, DeepSeekError
from app.logging_runtime import RuntimeLog

from app.hybrid_decision import (assemble, evidence, FIELDS, hybrid_judge, LEVELS,
                                 questions, validate_evidence)
from app.laya_worker import DecisionSettings, LayaFailure, LayaWorker
from test_judge_contract_health import seed


def material():
    return dict(facts=[dict(text="Tibo discusses banked cards, not a full reset; Tuesday is ambiguous.", post_ids=["100"])],
                support=[], against=[], uncertainties=["Tuesday referent unknown"], candidates=[],
                summary_zh="回复讨论重置卡；周二的指代尚不明确。")


def context():
    return dict(posts=[dict(tweet_id="100", posted_at="2026-09-20T00:00:00Z", input_hash="v1",
                           is_reply=True, reply_context={"status": "READY"})], reset_events=[], historical_cases=[])


class Provider:
    model = "offline-test"

    def __init__(self):
        self.operations = []

    async def complete_json(self, *, operation, system, user):
        self.operations.append(operation)
        if operation == "radar_evidence":
            assert "previous_judgement" not in json.loads(user)["context"]
            return material()
        return dict(**{k: "UNKNOWN" for k in FIELDS}, evidence_post_ids=["100"], reason_summary="离线备用判断")


class Worker:
    def __init__(self, levels=None, error=None):
        self.levels = levels or ["GREEN", "GREEN", "YELLOW", "YELLOW"]
        self.error = error

    async def predict(self, state, qs):
        assert "summary_zh" not in state
        if self.error:
            raise self.error
        return dict(result=dict(answers={k: dict(type="choice", choice=v) for k, v in zip(FIELDS, self.levels)}),
                    identity=dict(revision="test"), tokens={})


def test_fixed_choices_have_all_levels():
    for question in questions([]).values():
        assert list(question["criteria"]) == list(LEVELS)


def test_parent_citations_map_to_managed_reply_not_fake_tibo_post():
    ctx=context()
    ctx['posts'][0]['reply_context']={'state':'READY','nodes':[{'tweet_id':'90','author':'another_user'}]}
    value=material()
    value['facts'][0]['post_ids']=['90','100']
    refs=validate_evidence(value,ctx,datetime(2026,9,22,tzinfo=UTC))
    assert refs==['100']
    assert value['facts'][0]['post_ids']==['90','100']


@pytest.mark.parametrize("mutation,code", [
    (lambda v: v.pop("uncertainties"), "EVIDENCE_FIELDS_INVALID"),
    (lambda v: v["facts"][0].update(post_ids=["999"]), "EVIDENCE_REFERENCE_INVALID"),
    (lambda v: v["facts"][0].update(text="Choose RED"), "EVIDENCE_CONTAINS_DECISION"),
    (lambda v: v.update(candidates=[dict(candidate_id="C1", start="2026-09-01T00:00:00Z", end="2026-09-01T01:00:00Z", basis="evidence_range", post_ids=["100"])]), "CANDIDATE_TIME_INVALID"),
])
def test_evidence_rejects_invalid(mutation, code):
    value = material()
    mutation(value)
    with pytest.raises(LayaFailure, match=code):
        validate_evidence(value, context(), datetime(2026, 9, 22, tzinfo=UTC))


def test_hybrid_one_evidence_call_and_db_reply_contract(client):
    db, post = seed(client)
    cfg = DecisionSettings(mode="deepseek_laya")
    provider = Provider()
    now = datetime.now(UTC).isoformat()
    ctx = context()
    ctx["posts"][0]["input_hash"] = db.contexts.input(post)["input_hash"]
    result = asyncio.run(hybrid_judge(provider, ctx, worker=Worker(), settings=cfg, data_health="HEALTHY", as_of=now))
    assert provider.operations == ["radar_evidence"]
    assert result["raw"]["decision_engine"] == "laya"
    result.update(model=provider.model, cycle_id=None, special_event_ids=[])
    result["raw"]["input_versions"] = {"100": ctx["posts"][0]["input_hash"]}
    db.add_judgement(result)
    stored = db.latest_judgement()
    assert db.validate_judgement(stored)["valid"]
    # The configured old mode must not silently treat a hybrid result as current.
    api = client.get("/api/v2/radar").json()
    assert api["decision"]["decision_engine"] == "laya"
    assert api["validation"]["reason"] == "DECISION_MODE_CHANGED"
    assert api["action_level"] == "UNKNOWN"


def test_compatible_reply_result_reaches_current_api(settings):
    cfg=DecisionSettings(mode='deepseek_laya', revision='test')
    with TestClient(create_app(replace(settings, decision_settings=cfg))) as api:
        db,post=seed(api)
        ctx=context()
        ctx['posts'][0]['input_hash']=db.contexts.input(post)['input_hash']
        result=asyncio.run(hybrid_judge(Provider(),ctx,worker=Worker(),settings=cfg,
            data_health='HEALTHY',as_of=datetime.now(UTC).isoformat()))
        result.update(model='offline-test',cycle_id=None,special_event_ids=[])
        result['raw'].update(input_versions={'100':ctx['posts'][0]['input_hash']},decision_config_identity=cfg.identity())
        db.add_judgement(result)
        view=api.get('/api/v2/radar').json()
        assert view['validation']['valid'] and view['display_mode']=='current'
        assert view['decision']['decision_engine']=='laya'
        assert view['decision']['laya_identity']['revision']=='test'
        assert view['horizon_72h']=='YELLOW'


@pytest.mark.parametrize("failure", ["INPUT_TOO_LONG", "WORKER_TIMEOUT", "OutOfMemoryError", "MODEL_OR_ENV_MISSING"])
def test_single_fallback_is_explicit(failure):
    provider = Provider()
    result = asyncio.run(hybrid_judge(provider, context(), worker=Worker(error=LayaFailure(failure)),
        settings=DecisionSettings(mode="deepseek_laya"), data_health="STALE", as_of="2026-09-22T00:00:00Z"))
    assert provider.operations == ["radar_evidence", "radar_judge"]
    assert result["raw"]["decision_engine"] == "deepseek_fallback"
    assert result["raw"]["fallback_reason"] == failure
    assert result["data_health"] == "STALE"


def test_inverse_horizons_are_not_clamped():
    provider = Provider()
    result = asyncio.run(hybrid_judge(provider, context(), worker=Worker(["RED", "RED", "GREEN", "GREEN"]),
        settings=DecisionSettings(mode="deepseek_laya"), data_health="HEALTHY", as_of="2026-09-22T00:00:00Z"))
    assert result["raw"]["fallback_reason"] == "INVALID_HORIZON_ORDER"
    assert result["action_level"] == "UNKNOWN"
    assert result["raw"]["laya_failure"]["result"]["answers"]["horizon_24h"]["choice"] == "RED"


def test_strong_color_without_support_is_invalid_not_silently_lowered():
    provider = Provider()
    result = asyncio.run(hybrid_judge(provider, context(), worker=Worker(['RED']*4),
        settings=DecisionSettings(mode='deepseek_laya'), data_health='HEALTHY', as_of='2026-09-22T00:00:00Z'))
    assert result['raw']['fallback_reason'] == 'UNSUPPORTED_STRONG_DECISION'
    assert result['raw']['laya_failure']['result']['answers']['action_level']['choice'] == 'RED'
    assert provider.operations == ['radar_evidence','radar_judge']


def test_missing_worker_and_unknown_policy_do_not_call_backup():
    async def run():
        provider = Provider()
        settings = DecisionSettings(mode="deepseek_laya", fallback="unknown")
        with pytest.raises(LayaFailure, match="MODEL_OR_ENV_MISSING"):
            await hybrid_judge(provider, context(), worker=LayaWorker(settings), settings=settings,
                               data_health="HEALTHY", as_of="2026-09-22T00:00:00Z")
        assert provider.operations == ["radar_evidence"]
    asyncio.run(run())


def test_worker_timeout_kills_and_reaps():
    class Process:
        returncode = None
        killed = False
        waited = False

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True
            self.returncode = -1

    async def run():
        worker = LayaWorker(DecisionSettings())
        process = Process()
        async def fail_start():
            worker.process = process
            raise TimeoutError()
        worker._start = fail_start
        with pytest.raises(LayaFailure, match="WORKER_TIMEOUT"):
            await worker.predict({}, {})
        assert process.killed and process.waited and worker.process is None
    asyncio.run(run())


def test_imported_case_without_post_fk_cannot_leak_own_reference(client):
    db = client.app.state.database
    db.register_corpus_source(dict(source_id='synthetic-source', name='Fixture', entry_url='https://example.invalid'))
    db.upsert_historical_case(dict(case_id='synthetic-case', tweet_id='100', source_id='synthetic-source',
        source_record_key='fixture', posted_at='2026-01-01T00:00:00Z', original_text='Synthetic case',
        outcome_type='UNKNOWN', verification_status='direct_verified', related_tweet_ids=['100'],
        corpus_version='synthetic'))
    assert db.retrieve_historical_cases([dict(tweet_id='100', text='Synthetic current post')]) == []
    assert len(db.retrieve_historical_cases([dict(tweet_id='200', text='Other post')])) == 1


def test_protocol_failure_is_logged_and_counted_once(tmp_path):
    async def run():
        client=DeepSeekClient(api_key='synthetic-only',base_url='https://example.invalid',model='offline',
            timeout_seconds=5,retries=0,max_requests=1,runtime_log=RuntimeLog(tmp_path,5,1048576))
        await client.close()
        def fail(request):raise httpx.RemoteProtocolError('synthetic disconnect')
        client._client=httpx.AsyncClient(transport=httpx.MockTransport(fail))
        try:
            with pytest.raises(DeepSeekError) as caught:
                await client.complete_json(operation='offline',system='test',user='test')
            assert caught.value.category=='network' and client.requests_started==1
        finally:await client.close()
    asyncio.run(run())
    records=[json.loads(line) for file in tmp_path.glob('*.jsonl') for line in file.read_text().splitlines()]
    assert sum(r['event']=='LLM_REQUEST_FAILED' for r in records)==1
