"""Exercise worker's budget guard without importing any heavyweight dependency."""
import importlib.util
import sys
from types import SimpleNamespace

from app.config import REPOSITORY_ROOT


def test_token_guard_rejects_state_head_and_option_truncation(monkeypatch):
    spec = importlib.util.spec_from_file_location('crr_worker', REPOSITORY_ROOT / 'apps/laya-worker/worker.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Tokenizer:
        mask_token = '[MASK]'
        def __call__(self, value, **kwargs):
            return {'input_ids': value.split()}
    common = SimpleNamespace(render_options=lambda q: list(q['crit'].values()),
                             serialize_state=lambda state: state)
    monkeypatch.setitem(sys.modules, 'laya', SimpleNamespace(common=common))
    monkeypatch.setitem(sys.modules, 'laya.common', common)
    agent = SimpleNamespace(tok=Tokenizer(), cfg={'max_len':50, 'head_max_len':30},
        _to_internal=lambda q: {'t':'choice', 'ins':q['instructions'], 'crit':q['criteria']})
    q = {'action':dict(instructions='Choose one', criteria={'A':'normal', 'B':'unknown'})}
    assert not module.preflight(agent, 'short state', q)['action']['truncated']
    assert module.preflight(agent, 'long ' * 60, q)['action']['truncated']
    q['action']['instructions'] = 'too long ' * 20
    assert module.preflight(agent, 'short', q)['action']['truncated']
    q['action']['instructions'] = 'short'
    q['action']['criteria']['A'] = 'long ' * 50
    assert module.preflight(agent, 'short', q)['action']['truncated']
