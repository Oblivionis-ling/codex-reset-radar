from __future__ import annotations

import asyncio
import json

import pytest

from app.db import Database
from app.intelligence import candidate_record, event_records, validate_analysis, judge
from app.logging_runtime import RuntimeLog
from app.pipeline import IntelligencePipeline
from test_intelligence_pipeline import FakeDeepSeek


def effect(kind='FULL_RESET', stage='completed', quote='Usage is reset.'):
    return dict(event_type=kind, special_type='BANKED' if kind=='SPECIAL_RESET' else None,
                event_status='confirmed', canonical_eligible=True, scope='all_paid',
                execution_stage=stage, temporal_mode='future' if stage=='announced' else 'past',
                event_time_start=None, event_time_end=None, time_basis='post_time_proxy',
                evidence_quote=quote, summary='隔离用多效果测试', event_title='隔离用额度事件')


def analysis(effects):
    return dict(category='reset_confirmed', **effect(), effects=effects)


def test_future_special_never_becomes_published_event_even_if_model_says_confirmed():
    post=dict(id=1, tweet_id='synthetic-future', posted_at='2026-01-01T00:00:00Z',
              original_text='Card arrives tomorrow.')
    result=validate_analysis(analysis([effect('SPECIAL_RESET','announced','Card arrives tomorrow.')]), post)
    events=event_records(post,result)
    assert len(events)==1 and events[0][0]=='candidate'
    assert result['effects'][0]['canonical_eligible'] is False


def test_unknown_time_cannot_be_invented_from_post_time_and_mechanism_is_not_an_event():
    post=dict(id=1,tweet_id='synthetic-mechanism',posted_at='2026-01-01T00:00:00Z')
    uncertain=analysis([dict(effect('SPECIAL_RESET'),time_basis='unknown')])
    assert event_records(post,uncertain)[0][0]=='candidate'
    assert event_records(post,uncertain)[0][1]['occurred_at'] is None
    mechanism=analysis([dict(effect('SPECIAL_RESET'),claim_kind='mechanism_information')])
    assert event_records(post,mechanism)==[]


@pytest.mark.parametrize('effects',[
    [effect(quote='invented quote')],
    [dict(effect(),event_time_start='2026-02-02T00:00:00Z',event_time_end='2026-01-01T00:00:00Z')],
    [dict(effect(),canonical_eligible='false')],
])
def test_invalid_effect_is_rejected(effects):
    post=dict(tweet_id='synthetic-invalid',original_text='Usage is reset.')
    with pytest.raises(ValueError):
        validate_analysis(analysis(effects),post)


def test_category_contradiction_normalized_without_inventing_a_future_card():
    post=dict(tweet_id='synthetic-issued-card',original_text='Card is granted.')
    granted=dict(effect('SPECIAL_RESET',quote='Card is granted.'),claim_kind='occurrence')
    raw=dict(analysis([granted]),category='reset_announcement')
    result=validate_analysis(raw,post)
    assert result['category']=='reset_confirmed'
    assert result['model_category']=='reset_announcement'
    assert 'category' not in result['effects'][0]


def test_mixed_completed_and_planned_effect_does_not_erase_announcement():
    post=dict(tweet_id='synthetic-mixed-card',original_text='Card is granted. Another tomorrow.')
    granted=dict(effect('SPECIAL_RESET',quote='Card is granted.'),claim_kind='occurrence')
    planned=dict(effect('SPECIAL_RESET','announced','Another tomorrow.'),claim_kind='planned_occurrence')
    result=validate_analysis(dict(analysis([granted,planned]),category='reset_announcement'),post)
    assert result['category']=='reset_announcement'
    assert 'model_category' not in result


def test_ambiguous_candidate_does_not_fill_unknown_time_with_post_time():
    post=dict(id=1,tweet_id='synthetic-undated',posted_at='2026-01-01T00:00:00Z')
    result=candidate_record(post,dict(effect(),event_type='AMBIGUOUS',time_basis='unknown'))
    assert result['occurred_at_start'] is None


def test_plus_pro_scope_can_remain_full_and_cycle_eligible():
    post=dict(tweet_id='synthetic-plus-pro',original_text='Reset for all Plus and Pro users.')
    scoped=dict(effect(),scope='plus_pro',evidence_quote='Reset for all Plus and Pro users.')
    result=validate_analysis(analysis([scoped]),post)
    assert result['effects'][0]['event_type']=='FULL_RESET'
    assert result['effects'][0]['scope']=='plus_pro'
    assert result['effects'][0]['canonical_eligible'] is True


def test_judge_uses_full_reset_policy_but_does_not_force_a_colour():
    class PolicyModel(FakeDeepSeek):
        async def complete_json(self, *, operation, system, user):
            assert '主等级、24/48/72h 与预计窗口只回答完整重置' in user
            assert '不得仅凭其预告或确定性把完整重置主等级升色' in user
            assert '不得以它直接填充 estimated_start/estimated_end' in user
            result=await super().complete_json(operation=operation,system=system,user=user)
            result['action_level']='ORANGE'
            return result
    result=asyncio.run(judge(PolicyModel(),dict(posts=[],reset_events=[]),
                            data_health='HEALTHY',as_of='2026-01-01T00:00:00Z'))
    assert result['action_level']=='ORANGE'  # no hardcoded downgrade replaces the model


def test_judge_unwraps_required_schema_envelope_instead_of_silently_saving_unknown():
    class WrappedJudgeModel(FakeDeepSeek):
        async def complete_json(self, *, operation, system, user):
            value=await super().complete_json(operation=operation,system=system,user=user)
            return {'required_schema': value}
    result=asyncio.run(judge(WrappedJudgeModel(),dict(posts=[],reset_events=[]),
                            data_health='HEALTHY',as_of='2026-01-01T00:00:00Z'))
    assert result['action_level']=='GREEN'
    assert result['horizon_72h']=='ORANGE'
    assert 'required_schema' not in result['raw']


def test_judge_rejects_missing_levels_instead_of_silently_saving_unknown():
    class IncompleteJudgeModel(FakeDeepSeek):
        async def complete_json(self, *, operation, system, user):
            return {'reason_summary':'missing required levels'}
    with pytest.raises(ValueError,match='required fields are missing'):
        asyncio.run(judge(IncompleteJudgeModel(),dict(posts=[],reset_events=[]),
                          data_health='HEALTHY',as_of='2026-01-01T00:00:00Z'))


def test_multi_effect_product_flow_preserves_one_cycle_and_a_future_candidate(settings,tmp_path):
    class MultiEffectModel(FakeDeepSeek):
        async def complete_json(self, *, operation, system, user):
            if operation!='post_analysis':
                return await super().complete_json(operation=operation,system=system,user=user)
            self.calls.append(operation)
            return analysis([effect(), effect('SPECIAL_RESET','completed','Card is granted.'),
                             effect('FULL_RESET','announced','Another reset tomorrow.'),
                             effect('NON_RESET_QUOTA_BOOST','completed','Double quota today.')])

    async def run():
        database=Database(settings.database_path)
        database.initialize()
        model=MultiEffectModel()
        pipeline=IntelligencePipeline(database=database,client=model,
             runtime_log=RuntimeLog(settings.log_dir,5,1048576),collector_state={},repository_root=tmp_path)
        ingest=database.upsert_posts_detailed([dict(tweet_id='synthetic-dual-effect',source='test',
              posted_at='2026-01-01T00:00:00Z',text='Usage is reset. Card is granted. Another reset tomorrow. Double quota today.')])
        pipeline.enqueue_ingest(ingest)
        job=database.claim_post_job()
        await pipeline._process_post(job['payload']['post_id'])
        database.finish_job(job['id'])
        await pipeline.run_judge(as_of='2026-01-01T01:00:00Z',data_health='HEALTHY')
        assert len(database.list_reset_events())==2
        assert len(database.cycles())==1
        assert len(database.list_candidates())==1
        assert database.list_candidates()[0]['execution_stage']=='announced'
        assert len(database.list_posts(1)[0]['analysis']['effects'])==4
        assert database.latest_judgement()['prompt_version']
        await pipeline._process_post(job['payload']['post_id'])
        assert len(database.list_reset_events())==2 and len(database.list_candidates())==1
        assert model.calls.count('post_analysis')==1
        await pipeline.stop()
    asyncio.run(run())
