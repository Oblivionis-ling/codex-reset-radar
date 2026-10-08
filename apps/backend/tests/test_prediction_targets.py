from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.db import Database
from app.intelligence import judge
from app.prediction_contract import PREDICTION_CONTRACT_VERSION, PREDICTION_TARGETS, PredictionTargetsError
from app.prediction_ledger import PredictionLedger, LateInputRejected
from app.review_common import sha256_json, utc_text
from test_prediction_ledger import _database, _frozen_input, _records, _result, _unknown_targets
from test_context_evidence_snapshot import _seed_recent_posts_and_old_event


def _run(database, ledger, *, modern=True):
    frozen = _frozen_input(database)
    if modern:
        frozen['prediction_contract_version'] = PREDICTION_CONTRACT_VERSION
    run = ledger.begin_run(frozen, 'radar_judge', 'explicit-offline-runtime', 'focused', 'online', is_synthetic=True)
    attempt = ledger.begin_send(run.run_id, {'stage': 'radar_judge', 'request_hash': sha256_json(frozen),
                                            'input_frame_artifact_ref': run.input_frame_artifact_ref})
    return run, attempt


def _output(database, target='EXTRA_FULL', *, hours=1):
    value = _unknown_targets()[target]
    value.update(status='KNOWN', predicted_start=utc_text(datetime.now(UTC) + timedelta(hours=hours)),
                 prediction_form='point', precision='second', source_timezone='UTC', time_basis='model_inference',
                 lifecycle='planned', unresolved_reason=None,
                 evidence_post_ids=[database.judgement_context()['posts'][0]['tweet_id']])
    return value


def _valid_result(database=None):
    value = _result('GREEN')
    value['valid_until'] = utc_text(datetime.now(UTC) + timedelta(hours=2))
    if database is not None:
        context = database.judgement_context()
        value['raw'].update(input_versions=context['input_versions'], input_post_ids=list(context['input_versions']),
                            input_snapshot=context['input_snapshot'])
        value['cycle_id'] = (context.get('current_cycle') or {}).get('id')
    return value


@pytest.mark.parametrize('bad', ['missing', 'unexposed', 'wrong_target'])
def test_target_partial_does_not_turn_missing_or_bad_evidence_into_unknown(tmp_path, bad):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger)
    result = _valid_result(database)
    if bad == 'missing':
        del result['predictions']['BANKED']
        reason = 'MISSING_TARGET'
    else:
        result['predictions']['BANKED'] = _output(database, 'BANKED')
        if bad == 'unexposed':
            result['predictions']['BANKED']['evidence_post_ids'] = ['not-exposed']
            reason = 'EVIDENCE_NOT_EXPOSED_OR_VERSION_AMBIGUOUS'
        else:
            result['predictions']['BANKED']['target'] = 'EXTRA_FULL'
            reason = 'TARGET_KEY_MISMATCH'
    output = ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    committed = _records(database, 'output_committed')[0]['payload']
    assert committed['prediction_validation']['status'] == 'partial'
    assert committed['target_outputs']['EXTRA_FULL']['status'] == 'UNKNOWN'
    assert committed['target_outputs']['BANKED']['status'] is None
    assert committed['target_outputs']['BANKED']['validation']['reason'] == reason
    assert committed['output_available_at'] is None
    ledger.observe_output(output)
    assert database.get_judgement(output.judgement_id)['action_level'] == 'GREEN'
    projection = ledger.prediction_lines(database.get_judgement(output.judgement_id))
    assert projection['capabilities']['history_lines'] is True
    assert projection['capabilities']['model_targets'] == list(PREDICTION_TARGETS)
    lines = projection['lines']
    assert lines['EXTRA_FULL']['valid'] is True
    assert lines['EXTRA_FULL']['updated_at'] and lines['EXTRA_FULL']['valid_until']
    assert lines['BANKED']['valid'] is False and lines['BANKED']['output_available_at'] is None


def test_shared_run_question_versions_and_distinct_target_output_versions(tmp_path):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    runs, outputs, first_text_hashes = [], [], None
    for hour in (1, 2):
        run, attempt = _run(database, ledger)
        runs.append(run)
        result = _valid_result()
        result['predictions']['BANKED'] = _output(database, 'BANKED', hours=hour)
        outputs.append(ledger.commit_judge(run.run_id, attempt.attempt_id, result))
        ledger.observe_output(outputs[-1])
        with database.connect() as connection:
            hashes = {row[0] for row in connection.execute("SELECT content_hash FROM prediction_artifacts WHERE kind='text_content'")}
        if first_text_hashes is None:
            first_text_hashes = hashes
        else:
            assert hashes == first_text_hashes  # body and analysis summary both dedup
    assert runs[0].target_refs == runs[1].target_refs
    assert len(_records(database, 'forecast_version')) == 2
    assert len(_records(database, 'run_started')) == 2
    assert len(_records(database, 'attempt_started')) == 2
    committed = _records(database, 'output_committed')
    for target in PREDICTION_TARGETS:
        assert [entry['payload']['target_outputs'][target]['output_revision'] for entry in committed] == [1, 2]
        assert committed[0]['payload']['target_outputs'][target]['target_output_id'] != committed[1]['payload']['target_outputs'][target]['target_output_id']
    assert committed[0]['payload']['target_outputs']['BANKED']['predicted_start'] != committed[1]['payload']['target_outputs']['BANKED']['predicted_start']
    for question in _records(database, 'forecast_version'):
        assert question['payload']['version_role'] == 'question_version' and question['payload']['method'] is None
        assert 'facts' not in question['payload']
    with database.connect() as connection:
        body = database.get_post_by_tweet_id('990000000000000101')['original_text']
        assert connection.execute("SELECT count(*) FROM prediction_artifacts WHERE kind='text_content' AND content_hash=?", (sha256_json({'text': body}),)).fetchone()[0] == 1
    history = ledger.prediction_history('BANKED')
    assert [item['output_revision'] for item in history['items']] == [1, 2]
    assert [item['predicted_start'] for item in history['items']] == [entry['payload']['target_outputs']['BANKED']['predicted_start'] for entry in committed]
    assert all(item['method'] == 'model_inference' for item in history['items'])
    assert outputs[0].judgement_id != outputs[1].judgement_id


def test_missing_all_targets_is_failure_not_two_unknowns_and_full_contract_stays_required(tmp_path):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger)
    result = _valid_result()
    del result['predictions']
    with pytest.raises(PredictionTargetsError):
        ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    assert _records(database, 'output_committed') == []
    assert _records(database, 'output_observed') == []
    event = _records(database, 'attempt_event')[-1]['payload']
    assert event['reason_code'] == 'ALL_PREDICTION_TARGETS_REJECTED'
    assert event['output_available_at'] is None
    class MissingLevel:
        async def complete_json(self, **kwargs):
            return {'action_level': 'GREEN', 'predictions': _unknown_targets()}
    with pytest.raises(ValueError, match='required fields are missing'):
        asyncio.run(judge(MissingLevel(), database.judgement_context(), data_health='UNKNOWN'))


def test_atomic_shared_snapshot_rejects_both_targets_and_keeps_audit(tmp_path, monkeypatch):
    database, post = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger)
    result = _valid_result()
    result['predictions']['BANKED'] = _output(database, 'BANKED')
    inserted = []
    original_insert = database._insert_judgement
    def spy_insert(connection, *args, **kwargs):
        inserted.append(connection)
        return original_insert(connection, *args, **kwargs)
    monkeypatch.setattr(database, '_insert_judgement', spy_insert)
    database.upsert_posts_detailed([{'tweet_id': post['tweet_id'], 'text': 'Changed while both targets were in flight.',
                                    'posted_at': '2026-10-06T12:00:00Z', 'source': 'explicit-offline'}])
    with pytest.raises(LateInputRejected):
        ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    assert inserted == [] and _records(database, 'output_committed') == []
    rejection = _records(database, 'attempt_event')[-1]['payload']
    assert rejection['publication_status'] == 'rejected' and rejection['output_available_at'] is None
    assert set(rejection['structured_output']['predictions']) == set(PREDICTION_TARGETS)
    assert rejection['input_version_delta']


def test_modern_commit_reuses_immediate_connection_for_fresh_and_insert(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger)
    connections = []
    original_fresh, original_insert = ledger._fresh_judge_context, database._insert_judgement
    def fresh(connection, *args):
        with database.connect() as nested:
            assert nested is connection and nested.in_transaction
        connections.append(connection)
        return original_fresh(connection, *args)
    def insert(connection, *args, **kwargs):
        with database.connect() as nested:
            assert nested is connection and nested.in_transaction
        connections.append(connection)
        return original_insert(connection, *args, **kwargs)
    monkeypatch.setattr(ledger, '_fresh_judge_context', fresh)
    monkeypatch.setattr(database, '_insert_judgement', insert)
    ledger.commit_judge(run.run_id, attempt.attempt_id, _valid_result())
    assert len(connections) == 2 and connections[0] is connections[1]


def test_legacy_producer_without_explicit_contract_is_not_retrofit_as_two_targets(tmp_path):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger, modern=False)
    result = _valid_result()
    del result['predictions']
    output = ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    assert 'BANKED' not in run.target_refs
    assert 'target_outputs' not in _records(database, 'output_committed')[0]['payload']
    assert len(_records(database, 'forecast_version')) == 1
    projection = ledger.prediction_lines(database.get_judgement(output.judgement_id))
    assert projection['lines']['BANKED']['status'] is None
    assert projection['lines']['BANKED']['validation_reason'] == 'LEGACY_TARGET_NOT_IMPLEMENTED'
    assert projection['capabilities']['model_targets'] == []


def test_history_is_bounded_includes_true_boundaries_failures_observations_and_never_writes(tmp_path, monkeypatch):
    database, _ = _database(tmp_path)
    ledger = PredictionLedger(database)
    for index in range(4):
        run, attempt = _run(database, ledger)
        output = ledger.commit_judge(run.run_id, attempt.attempt_id, _valid_result())
        ledger.observe_output(output)
    failed, attempt = _run(database, ledger)
    ledger.append_attempt_event(failed.run_id, attempt.attempt_id, 'request_failure', failure_terminal=True,
                                reason_code='SYNTHETIC_OFFLINE_FAILURE', output_available_at=None)
    with database.connect() as connection:
        # A processing run must not leak into radar history.
        connection.execute("INSERT INTO prediction_ledger(record_id,kind,run_id,recorded_at,payload_json) VALUES(?,?,?,?,?)",
                           ('processing-only', 'run_started', 'unrelated-processing', utc_text(), '{"stage":"post_analysis"}'))
    traces = []
    original_ro = ledger._read_connection
    @contextmanager
    def traced_ro():
        with original_ro() as connection:
            assert connection.execute('PRAGMA query_only').fetchone()[0] == 1
            connection.set_trace_callback(traces.append)
            yield connection
    monkeypatch.setattr(ledger, '_read_connection', traced_ro)
    with database.connect() as connection:
        count_before = connection.execute('SELECT count(*) FROM prediction_ledger').fetchone()[0]
    history = ledger.prediction_history('BANKED', limit=2)
    assert history['count'] == 4 and history['truncated'] is True and len(history['items']) == 2
    assert history['first_item']['ledger_seq'] < history['items'][0]['ledger_seq']
    assert history['last_item']['record_id'] == history['last_record_id']
    assert any(item.get('reason_code') == 'SYNTHETIC_OFFLINE_FAILURE' for item in history['attempts'])
    assert all(item['run_id'] != 'unrelated-processing' for item in history['attempts'])
    assert all(item['output_available_at'] for item in [*history['items'], history['first_item']])
    assert history['item_schema'] == 'prediction-history-line-v1'
    assert all('payload' not in item and 'payload_json' not in item for item in [*history['items'], *history['attempts']])
    assert all('LIMIT' in sql.upper() for sql in traces if sql.upper().startswith('SELECT * FROM PREDICTION_LEDGER'))
    ledger.prediction_lines(database.latest_judgement())
    with database.connect() as connection:
        assert connection.execute('SELECT count(*) FROM prediction_ledger').fetchone()[0] == count_before


def test_normal_reference_full_descriptor_and_outside_window_bodies_are_frozen_in_actual_request(tmp_path):
    database = Database(tmp_path / 'normal-material.sqlite')
    database.initialize()
    now, source_id, event = _seed_recent_posts_and_old_event(database)
    event.update(event_type='FULL_RESET', special_type=None, event_key='explicit-normal-anchor',
                 provenance={'time_precision': 'day', 'time_form': 'date', 'source_timezone': 'UTC+8'},
                 time_basis='post_time_proxy')
    database.upsert_reset_event(event, is_synthetic=True)
    context = database.judgement_context()
    seen = []
    class Capture:
        async def complete_json(self, **kwargs):
            seen.append(json.loads(kwargs['user'].splitlines()[-1]))
            return _valid_result()
    ledger = PredictionLedger(database)
    material = []
    @contextmanager
    def freeze(request):
        material.append(request)
        frozen = _frozen_input(database)
        frozen['prediction_contract_version'] = PREDICTION_CONTRACT_VERSION
        frozen['context'] = request['context']
        frozen['public_prompt'] = {'system': request['system'], 'user_prefix': request['user_prefix']}
        frozen['judge_schema'] = request['schema']
        run = ledger.begin_run(frozen, 'radar_judge', 'offline-runtime', 'focused', 'online', is_synthetic=True)
        yield run
    asyncio.run(judge(Capture(), context, data_health='UNKNOWN', request_scope=freeze))
    sent = seen[0]['context']
    descriptor = sent['normal_reference']
    assert descriptor['precision'] == 'day' and descriptor['source_timezone'] == 'UTC+8'
    assert descriptor['prediction_form'] == descriptor['time_form'] == 'proxy'
    assert descriptor['anchor_limitation'] == 'POST_TIME_PROXY_NOT_ACTUAL_START'
    assert descriptor['reference_only'] is True and descriptor['not_prediction_evidence'] is True
    assert sent['default_reference_last_full_plus_7d'] == descriptor['estimated_at']
    assert sent['current_cycle'] is not None and sent['last_full_reset'] is not None
    source = next(post for post in sent['event_source_posts'] if post['tweet_id'] == source_id)
    assert source['text'] == database.get_post_by_tweet_id(source_id)['original_text']
    assert source_id in context['input_snapshot']['post_analysis_versions']
    payload = _records(database, 'run_started')[0]['payload']
    frame = ledger._restore_texts(ledger._load_artifact(payload['input_frame_artifact_ref']['artifact_id']))
    assert frame['context']['normal_reference'] == descriptor
    assert frame['context']['event_source_posts'][0]['text'] == source['text']


def test_normal_anchor_change_and_observation_failure_never_backfill_on_get(tmp_path, monkeypatch):
    database, post = _database(tmp_path)
    ledger = PredictionLedger(database)
    saved = database.upsert_reset_event({'event_key': 'normal-anchor-1', 'event_type': 'FULL_RESET',
        'occurred_at': utc_text(datetime.now(UTC)), 'source_post_id': post['post_id'], 'title': 'Explicit synthetic Full',
        'summary': 'Full complete', 'time_basis': 'explicit_text', 'scope': 'all_paid', 'execution_stage': 'completed',
        'evidence_post_ids': [post['tweet_id']], 'provenance': {'time_form': 'point', 'time_precision': 'second', 'source_timezone': 'UTC'}}, is_synthetic=True)
    normal = ledger.record_normal_baseline(saved, is_synthetic=True)
    assert normal and ledger.prediction_lines(None)['lines']['NORMAL_WEEKLY']['valid'] is True
    saved['occurred_at'] = utc_text(datetime.now(UTC) + timedelta(seconds=1))
    saved['event_key'] = 'normal-anchor-2'
    saved = database.upsert_reset_event(saved, is_synthetic=True)
    assert ledger.prediction_lines(None)['lines']['NORMAL_WEEKLY']['validation_reason'] == 'ANCHOR_CHANGED'
    original_append = ledger._append_record
    def reject_observation(connection, kind, payload, **kwargs):
        if kind == 'output_observed':
            raise sqlite3.OperationalError('explicit synthetic observation failure')
        return original_append(connection, kind, payload, **kwargs)
    monkeypatch.setattr(ledger, '_append_record', reject_observation)
    ledger.record_normal_baseline(saved, is_synthetic=True)
    marker = _records(database, 'attempt_event')[-1]['payload']
    assert marker['reason_code'] == 'NORMAL_OBSERVATION_FAILED' and marker['output_available_at'] is None
    count = len(_records(database, 'normal_baseline'))
    for _ in range(2):
        line = ledger.prediction_lines(None)['lines']['NORMAL_WEEKLY']
        assert line['output_available_at'] is None and line['validation_reason'] == 'OUTPUT_AVAILABILITY_PENDING'
    assert len(_records(database, 'normal_baseline')) == count


def test_formal_relative_output_cannot_claim_utc_from_a_utc_plus_8_source_token(tmp_path):
    database, original = _database(tmp_path)
    posted = utc_text(datetime.now(UTC) - timedelta(minutes=1))
    post = database.upsert_posts_detailed([{'tweet_id': original['tweet_id'],
        'text': 'Banked starts 明天10:30 UTC+8.', 'posted_at': posted, 'source': 'explicit-offline'}])[0]
    version = database.contexts.input(database.get_post(post['post_id']))['input_hash']
    database.save_analysis(post['post_id'], version, 'offline', 'offline', {'category': 'other',
        'context_sufficient': True, '_input_hash': version, 'summary': 'Explicit offline relative fixture.'})
    ledger = PredictionLedger(database)
    run, attempt = _run(database, ledger)
    result = _valid_result(database)
    value = _output(database, 'BANKED')
    value.update(predicted_start=None, prediction_form='relative', precision='minute', expression='明天10:30 UTC+8',
                 source_timezone='UTC', relative_anchor_at=posted, time_basis='relative_to_post')
    result['predictions']['BANKED'] = value
    output = ledger.commit_judge(run.run_id, attempt.attempt_id, result)
    child = _records(database, 'output_committed')[0]['payload']['target_outputs']['BANKED']
    assert child['validation']['reason'] == 'RELATIVE_CLOCK_SEMANTICS_NOT_VERIFIED'
    assert child['status'] is None
    ledger.observe_output(output)
    assert ledger.prediction_lines(database.get_judgement(output.judgement_id))['lines']['BANKED']['output_available_at'] is None
