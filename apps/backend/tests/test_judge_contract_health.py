from datetime import UTC, datetime, timedelta
import json
import asyncio
import time
import pytest

from test_content_policies import judgement, policy
from test_reply_context import reply, node, complete


def seed(client):
    db = client.app.state.database
    post = reply(db)
    complete(db, [node(), node('90', None, 'other', 'Synthetic question')])
    post = db.get_post(post['id'])
    for name in ('profile_monitor', 'replies_monitor'):
        client.post('/api/v2/collector/heartbeat', json={'component': name, 'state': 'healthy'})
    now = datetime.now(UTC)
    value = judgement(['100']) | {
        'created_at': now.isoformat(), 'valid_until': (now + timedelta(hours=1)).isoformat(),
        'raw': {'input_versions': {'100': db.contexts.input(post)['input_hash']}},
    }
    db.add_judgement(value)
    return db, post


def test_database_read_reply_versions_validate_and_reach_radar(client):
    db, post = seed(client)
    stored = db.latest_judgement()
    assert 'raw' in stored and 'raw_json' not in stored
    assert stored['raw']['input_versions']['100'] == db.contexts.input(post)['input_hash']
    assert db.judgement_is_usable(stored)
    radar = client.get('/api/v2/radar').json()
    assert radar['action_level'] == 'GREEN'
    assert radar['horizon_72h'] == 'ORANGE'


@pytest.mark.parametrize('raw,reason', [('{broken','CONTRACT_ERROR'), ('[]','CONTRACT_ERROR'),
    ('{"input_versions": []}','INVALID_INPUT_VERSIONS'), ('{}','MISSING_INPUT_VERSION'),
    ('{"input_versions": {}, "input_post_ids": ["100"]}','INCOMPLETE_INPUT_VERSIONS')])
def test_storage_corruption_has_reason_and_safe_api(client,raw,reason):
    db,_=seed(client)
    with db.connect() as c:c.execute('UPDATE radar_judgements SET raw_json=?',(raw,))
    radar=client.get('/api/v2/radar').json()
    assert radar['validation']['reason']==reason
    assert radar['action_level']=='UNKNOWN'
    assert radar['data_health']=='HEALTHY'


def test_dual_representation_conflict_is_rejected(client):
    db,_=seed(client)
    result=db.normalize_judgement({**db.latest_judgement(),'raw_json':'{"different":true}'})
    assert 'CONFLICTING_RAW_REPRESENTATIONS' in result['contract_errors']
    assert not db.judgement_is_usable(result)


def test_expiry_cycle_parent_and_policy_protections(client):
    db,post=seed(client)
    j=db.latest_judgement()
    assert db.validate_judgement(j,at=datetime.now(UTC)+timedelta(hours=2))['reason']=='EXPIRED'
    assert db.validate_judgement({**j,'cycle_id':999})['reason']=='CYCLE_CHANGED'
    with db.connect() as c:
        c.execute("UPDATE reply_context_nodes SET body_json=json_set(body_json,'$.text','Changed parent') WHERE tweet_id='90'")
    assert db.validate_judgement(j)['reason']=='INPUT_CHANGED'
    db.upsert_content_policy(policy('100',post['text_hash']))
    assert db.validate_judgement(j)['reason']=='CONTENT_RESTRICTED'


def test_deleted_evidence_is_rejected(client):
    db,_=seed(client)
    j=db.latest_judgement()
    j['evidence_post_ids']=['not-existent']
    assert db.validate_judgement(j)['reason']=='EVIDENCE_MISSING'


def test_stale_generation_stays_last_known_after_recovery(client):
    db,_=seed(client)
    with db.connect() as c:c.execute("UPDATE radar_judgements SET data_health='STALE'")
    radar=client.get('/api/v2/radar').json()
    assert radar['validation']['valid']
    assert radar['current_data_health']=='HEALTHY'
    assert radar['judgement_data_health']=='STALE'
    assert radar['display_mode']=='last_known' and radar['action_level']=='UNKNOWN'
    assert radar['last_known_result']['action_level']=='GREEN'


def test_model_unknown_is_not_a_validation_failure(client):
    db,_=seed(client)
    with db.connect() as c:c.execute("UPDATE radar_judgements SET action_level='UNKNOWN',horizon_24h='UNKNOWN',horizon_48h='UNKNOWN',horizon_72h='UNKNOWN'")
    radar=client.get('/api/v2/radar').json()
    assert radar['display_mode']=='model_unknown'
    assert radar['reason_summary']=='Synthetic policy fixture.'


def test_health_decays_get_is_read_only_and_old_heartbeat_cannot_recover(client):
    from app.collector_health import collector_health
    seed(client)
    states=client.app.state.collector_state
    original=json.dumps(states,sort_keys=True)
    for _ in range(3):client.get('/api/v2/health');client.get('/api/v2/radar')
    assert json.dumps(states,sort_keys=True)==original
    future=collector_health(states,at=datetime.now(UTC)+timedelta(minutes=16))
    assert future['data_health']=='STALE'
    assert future['collector']['profile_monitor']['reported_state']=='healthy'
    assert future['collector']['profile_monitor']['state']=='stale'
    response=client.post('/api/heartbeat',json={'component':'profile_monitor','observed_at':'2020-01-01T00:00:00Z'}).json()
    assert response['reason']=='OLD_HEARTBEAT'
    response=client.post('/api/heartbeat',json={'component':'profile_monitor','observed_at':'2099-01-01T00:00:00Z'}).json()
    assert response['reason']=='CLOCK_SKEW'


def test_search_cannot_mask_stale_profile_and_replies(client):
    seed(client)
    for name in ('profile_monitor','replies_monitor'):
        client.app.state.collector_state[name]['last_seen_at']='2020-01-01T00:00:00Z'
    client.post('/api/heartbeat',json={'component':'search_backfill'})
    health=client.get('/api/v2/health').json()
    assert health['data_health']=='STALE'
    assert health['collector']['search_backfill']['state']=='healthy'
    assert health['collector']['profile_monitor']['state']=='stale'
    assert client.get('/api/v2/radar').json()['display_mode']=='last_known'


def test_pending_wait_bounded_and_retries_dont_block(client,tmp_path,monkeypatch):
    from test_reply_context import pipeline,ContextModel
    db,post=seed(client)
    p=pipeline(db,tmp_path,ContextModel())
    db.enqueue_post(post['id'],p.identity(post))
    tick=[100.0];monkeypatch.setattr('app.pipeline.time.monotonic',lambda:tick[0])
    p.request_judge('first')
    tick[0]=130;p.request_judge('duplicate')
    assert p._judge_requested_at==100 and p.judge_waiting()
    tick[0]=160
    assert not p.judge_waiting()
    with db.connect() as c:c.execute("UPDATE processing_jobs SET next_attempt_at='2099-01-01T00:00:00Z' WHERE job_type='POST_PROCESSING'")
    tick[0]=104
    assert not p.judge_waiting()
    with db.connect() as c:c.execute("UPDATE processing_jobs SET status='FAILED' WHERE job_type='POST_PROCESSING'")
    assert not p.judge_waiting()


def test_special_preview_keeps_events_and_cycles_unchanged(client):
    db,post=seed(client)
    stamp=datetime.now(UTC).isoformat()
    with db.connect() as c:c.execute('UPDATE tibo_posts SET posted_at=? WHERE id=?',(stamp,post['id']))
    post=db.get_post(post['id'])
    db.upsert_candidate({'candidate_key':'preview','event_type':'SPECIAL_RESET','special_type':'BANKED',
        'execution_stage':'announced','evidence_post_ids':['100'],'summary':'Synthetic preview',
        'analysis':{'_input_hash':db.contexts.input(post)['input_hash'],'context_sufficient':True}})
    before=(db.counts()['reset_events'],db.cycles())
    preview=client.get('/api/v2/radar').json()['special_announcements']
    assert len(preview)==1 and preview[0]['scheduled_at'] is None
    assert (db.counts()['reset_events'],db.cycles())==before
    db.upsert_content_policy(policy('100',post['text_hash']))
    assert db.special_announcements()==[]


def test_recovery_requests_judge_without_rewriting_stale_result(client,tmp_path):
    from test_reply_context import pipeline,ContextModel
    db,_=seed(client);p=pipeline(db,tmp_path,ContextModel())
    # The production callback captures its own pipeline; its clock-independent
    # scheduler also detects a natural freshness transition without any GET write.
    p.collector_state.update(client.app.state.collector_state)
    assert p._last_data_health=='STALE' and p._data_health()=='HEALTHY'


def test_semantic_boundary_is_in_same_judge_prompt(client,tmp_path):
    from test_reply_context import pipeline,ContextModel
    db,post=seed(client);model=ContextModel();p=pipeline(db,tmp_path,model)
    asyncio.run(p._process_post(post['id']))
    asyncio.run(p.run_judge())
    call=[x for x in model.inputs if x['operation']=='radar_judge'][-1]
    assert '不能擅自拆出第二个完整重置承诺' in call['system']
    assert 'pending_inputs' in call['user']
    assert '2101352781219258527' not in call['system']


def test_judge_single_flight_and_late_snapshot_rejected(client,tmp_path):
    from test_reply_context import pipeline,ContextModel
    db,post=seed(client)
    class Slow(ContextModel):
        active=0
        peak=0
        change=False
        async def complete_json(self,**kwargs):
            if kwargs['operation']=='radar_judge':
                self.active+=1;self.peak=max(self.peak,self.active)
                await asyncio.sleep(.01)
                if self.change:
                    with db.connect() as c:c.execute("UPDATE reply_context_nodes SET body_json=json_set(body_json,'$.text','New parent') WHERE tweet_id='90'")
                self.active-=1
            return await super().complete_json(**kwargs)
    model=Slow();p=pipeline(db,tmp_path,model)
    asyncio.run(p._process_post(post['id']))
    async def concurrent():await asyncio.gather(p.run_judge(),p.run_judge())
    asyncio.run(concurrent());assert model.peak==1
    before=db.counts()['radar_judgements'];model.change=True
    with pytest.raises(ValueError,match='input changed'):asyncio.run(p.run_judge())
    assert db.counts()['radar_judgements']==before and p._judge_dirty


def test_heartbeat_recovery_coalesces_and_preserves_original_health(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_reply_context import ContextModel
    with TestClient(create_app(settings,intelligence_client=ContextModel())) as current:
        for name in ('profile_monitor','replies_monitor'):
            current.post('/api/heartbeat',json={'component':name,'observed_at':'2020-01-01T00:00:00Z'})
        triggers=[];current.app.state.pipeline.request_judge=triggers.append
        for name in ('profile_monitor','replies_monitor'):
            current.post('/api/heartbeat',json={'component':name})
        assert triggers==['collector_health_transition']
        for _ in range(3):current.get('/api/v2/health');current.get('/api/v2/radar')
        assert triggers==['collector_health_transition']


def test_special_preview_expiry_and_cancellation(client):
    db,post=seed(client)
    record={'candidate_key':'preview','event_type':'SPECIAL_RESET','special_type':'BANKED',
        'execution_stage':'announced','evidence_post_ids':['100'],'summary':'Synthetic preview',
        'analysis':{'_input_hash':db.contexts.input(post)['input_hash'],'context_sufficient':True}}
    db.upsert_candidate(record)
    assert not db.special_announcements(at=datetime.now(UTC)+timedelta(days=8))
    db.upsert_candidate({**record,'status':'CANCELLED'})
    assert not db.special_announcements()
