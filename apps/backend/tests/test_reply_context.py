import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.db import Database
from app.pipeline import IntelligencePipeline
from app.logging_runtime import RuntimeLog
from app.reply_context import ReplyContexts
from test_intelligence_pipeline import FakeDeepSeek


@pytest.fixture
def db(tmp_path):
    db=Database(tmp_path/'isolated.db');db.initialize();return db


def reply(db, tid='100'):
    db.upsert_posts([{'tweet_id':tid,'text':'Yes, Tuesday.','posted_at':'2026-09-20T01:00:00Z','is_reply':True}])
    return db.get_post_by_tweet_id(tid)


def node(tid='100', parent='90', author='thsottiaux',text='Yes, Tuesday.'):
    return {'tweet_id':tid,'author':author,'text':text,'posted_at':'2026-09-19T01:00:00Z',
            'parent_id':parent,'relation_source':'x_replied_to_field','completeness':'complete','language':'en'}


def complete(db,nodes,tid='100'):
    db.contexts.ensure(tid);job=db.contexts.claim();assert job
    assert db.contexts.complete(job['id'],job['lease'],nodes)
    return job


def test_direct_parent_chain_excludes_unrelated_root_and_other_authors_not_tibo(db):
    p=reply(db)
    complete(db,[node(),node('90','80','other','Will there be a banked reset?'),node('80',None,'ancestor','Background')])
    context=db.contexts.snapshot(p)
    assert [n['tweet_id'] for n in context['nodes']]==['90','80']
    assert context['nodes'][0]['author']=='other'
    assert db.counts()['tibo_posts']==1
    assert db.counts()['reset_events']==0


def test_wrong_relationship_and_quote_rejected(db):
    reply(db);db.contexts.ensure('100');job=db.contexts.claim()
    with pytest.raises(ValueError,match='ancestor chain'):
        db.contexts.complete(job['id'],job['lease'],[node(),node('88',None,'quoted')])
    with pytest.raises(ValueError,match='observed'):
        db.contexts.complete(job['id'],job['lease'],[{**node(),'relation_source':'previous_DOM_card'}])


def test_hash_changes_only_on_semantic_context_and_shared_parent(db):
    p=reply(db);other=reply(db,'101');before=db.contexts.input(p)['input_hash']
    complete(db,[node(),node('90',None,'other','Question')])
    after=db.contexts.input(p)['input_hash'];assert before!=after
    complete(db,[node('101'),node('90',None,'other','Question')],tid='101')
    assert db.contexts.input(p)['input_hash']==after
    assert db.contexts.snapshot(other)['nodes'][0]['tweet_id']=='90'
    with db.connect() as c:
        assert c.execute("SELECT count(*) FROM reply_context_history WHERE tweet_id='90'").fetchone()[0]==1


def test_lease_recovery_stale_results_rejected_and_bounded_attempts(db):
    reply(db);db.contexts.ensure('100');a=db.contexts.claim()
    assert db.contexts.claim() is None
    with db.connect() as c:c.execute("UPDATE processing_jobs SET next_attempt_at='2000-01-01' WHERE id=?",(a['id'],))
    b=ReplyContexts(db).claim();assert b and b['lease']!=a['lease']
    assert not db.contexts.complete(a['id'],a['lease'],[node()])
    assert db.contexts.complete(b['id'],b['lease'],[], 'LOGIN_REQUIRED')
    db.contexts.ensure('100');assert db.contexts.claim() is None
    assert db.contexts.job('100')['last_error']=='LOGIN_REQUIRED'
    assert db.pending_job_count()==0


def test_depth_length_and_identity_validation(db):
    reply(db);db.contexts.ensure('100');job=db.contexts.claim()
    with pytest.raises(ValueError,match='bound'):
        db.contexts.complete(job['id'],job['lease'],[node()]*5)
    with pytest.raises(ValueError,match='author'):
        db.contexts.complete(job['id'],job['lease'],[node(author='someone_else')])


def test_replay_excludes_later_observation(db):
    p=reply(db);complete(db,[node(),node('90',None,'other')])
    assert db.contexts.snapshot(p,as_of='2026-09-19T02:00:00Z')['nodes']==[]


def test_replay_does_not_substitute_later_canonical_edit(db):
    reply(db,'90');reply(db)
    complete(db,[node(),node('90',None,'thsottiaux')])
    with db.connect() as c:
        c.execute("UPDATE reply_context_nodes SET observed_at='2026-09-19T02:00:00Z'")
        c.execute("UPDATE tibo_posts SET original_text='Later edited body' WHERE tweet_id='90'")
    assert db.contexts.node('90',as_of='2026-09-19T03:00:00Z') is None


class ContextModel(FakeDeepSeek):
    def __init__(self):super().__init__();self.inputs=[];self.on_analysis=None
    async def complete_json(self,**kwargs):
        self.inputs.append(kwargs)
        result=await super().complete_json(**kwargs)
        if kwargs['operation']=='post_analysis':
            if self.on_analysis:self.on_analysis();self.on_analysis=None
            result['context_sufficient']=True
        return result


def pipeline(db,tmp_path,model):
    return IntelligencePipeline(database=db,client=model,runtime_log=RuntimeLog(tmp_path/'logs',5,1048576),collector_state={},repository_root=tmp_path)


def test_same_pipeline_reanalysis_translation_judge_context_and_idempotency(db,tmp_path):
    p=reply(db);model=ContextModel();pipe=pipeline(db,tmp_path,model)
    asyncio.run(pipe._process_post(p['id']))
    assert model.calls.count('post_analysis')==1
    complete(db,[node(),node('90',None,'other','When will the banked reset arrive?')])
    assert db.list_posts()[0]['analysis'] is None
    asyncio.run(pipe._process_post(p['id']))
    asyncio.run(pipe.run_judge())
    assert model.calls.count('post_analysis')==2
    asyncio.run(pipe._process_post(p['id']))
    assert model.calls.count('post_analysis')==2
    assert model.calls.count('post_translation')==2
    for op in ('post_analysis','post_translation','radar_judge'):
        last=[x for x in model.inputs if x['operation']==op][-1]
        assert 'When will the banked reset arrive?' in last['user']
    assert db.list_posts()[0]['analysis']['_input_hash']==db.contexts.input(db.get_post(p['id']))['input_hash']


def test_late_model_result_cannot_replace_new_input(db,tmp_path):
    p=reply(db);model=ContextModel();pipe=pipeline(db,tmp_path,model)
    model.on_analysis=lambda:complete(db,[node(),node('90',None,'other','Changed input')])
    asyncio.run(pipe._process_post(p['id']))
    with db.connect() as c:assert c.execute('SELECT count(*) FROM post_analysis').fetchone()[0]==0
    assert db.pending_job_count()==1


def test_parent_content_policy_applies_through_context(db):
    p=reply(db)
    parent=reply(db,'90')
    complete(db,[node(),node('90',None,'thsottiaux','Yes, Tuesday.')])
    from test_content_policies import policy
    parent=db.get_post(parent['id'])
    db.upsert_content_policy(policy('90',parent['text_hash']))
    context=db.contexts.snapshot(p)
    assert context['nodes']==[] and 'CONTENT_RESTRICTED' in context['missing']


def test_cached_canonical_parent_does_not_require_browser_or_duplicate_post(db):
    reply(db,'90')
    cached=db.contexts.node('90')
    assert cached['relation_source']=='canonical_body_only'
    reply(db)
    complete(db,[{**node(),'posted_at':'2026-09-20T01:00:00Z'},cached])
    assert db.counts()['tibo_posts']==2
    assert db.contexts.snapshot(db.get_post_by_tweet_id('100'))['nodes'][0]['tweet_id']=='90'


def test_durable_context_job_to_actual_pipeline_and_api(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_intelligence_pipeline import wait_until
    fake=ContextModel()
    with TestClient(create_app(settings,intelligence_client=fake)) as client:
        for name in ('profile_monitor','replies_monitor'):
            client.post('/api/heartbeat',json={'component':name})
        posted=datetime.now(UTC).isoformat().replace('+00:00','Z')
        data={'tweets':[{'tweet_id':'100','text':'Yes, Tuesday.','created_at':posted,'is_reply':True,'author':'thsottiaux'}]}
        client.post('/api/v2/collector/posts',json=data)
        job=client.post('/api/v2/context/claim').json()['job'];assert job
        n1={**node(),'posted_at':posted};n2={**node('90',None,'other','Will the banked reset arrive Tuesday?'),'posted_at':posted}
        receipt=client.post('/api/v2/context/result',json={**job,'nodes':[n1,n2]})
        assert receipt.json()['accepted']
        wait_until(lambda:client.get('/api/v2/posts').json()['items'][0]['analysis_status']=='COMPLETED')
        wait_until(lambda:client.get('/api/v2/radar').json()['judgement_id'] is not None)
        response=client.get('/api/v2/posts').json()['items'][0]
        assert response['reply_context']['nodes'][0]['author']=='other'
        assert response['analysis']['_input_hash']==response['input_hash']
        before=len(fake.calls)
        client.post('/api/v2/collector/posts',json=data)
        assert client.post('/api/v2/context/claim').json()['job'] is None
        assert len(fake.calls)==before
        assert client.get('/api/v2/resets').json()['items']==[]
        triggers=[]
        client.app.state.pipeline.request_judge=triggers.append
        assert client.post('/api/v2/context/retry/100').json()['queued']
        repeated=client.post('/api/v2/context/claim').json()['job']
        assert client.post('/api/v2/context/result',json={**repeated,'nodes':[n1,n2]}).json()['accepted']
        assert 'reply_context_updated' not in triggers
        assert client.app.state.database.pending_job_count()==0


def test_missing_context_cannot_promote_even_model_suggests_event(db,tmp_path):
    p=reply(db)
    class Insufficient(ContextModel):
        async def complete_json(self,**kwargs):
            result=await super().complete_json(**kwargs)
            if kwargs['operation']=='post_analysis':result['context_sufficient']=False
            return result
    asyncio.run(pipeline(db,tmp_path,Insufficient())._process_post(p['id']))
    assert db.get_post(p['id'])['analysis_status']=='INSUFFICIENT_INPUT'
    assert db.counts()['reset_events']==0


def test_human_fields_remain_protected_on_model_origin_event(db,tmp_path,monkeypatch):
    p=reply(db)
    monkeypatch.setattr(db,'list_reset_events',lambda limit: [{
        'id':12,'evidence_post_ids':['100'],
        'provenance':{'source':'deepseek_semantic_analysis','human_adjudications':[{'fields':['event_type']}]}}])
    asyncio.run(pipeline(db,tmp_path,ContextModel())._process_post(p['id']))
    review=db.get_state(f"reply_review:{p['id']}")
    assert review['preserved_event_ids']==[12]
    assert review['state']=='NEEDS_HUMAN_REVIEW'


def test_expired_browser_lease_never_retries_forever(db):
    reply(db);db.contexts.ensure('100')
    for _ in range(3):
        job=db.contexts.claim();assert job
        with db.connect() as c:c.execute("UPDATE processing_jobs SET next_attempt_at='2000-01-01' WHERE id=?",(job['id'],))
    assert db.contexts.claim() is None
    assert db.contexts.job('100')['status']=='FAILED'
