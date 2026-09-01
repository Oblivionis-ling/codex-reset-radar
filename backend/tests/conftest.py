from __future__ import annotations

import pytest

import app.main as backend_main


@pytest.fixture(autouse=True)
def disable_live_github_mirror_for_tests(monkeypatch, tmp_path):
    """Keep TestClient suites offline; mirror behavior has dedicated unit coverage."""

    monkeypatch.setenv("GITHUB_MIRROR_ENABLED", "false")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(backend_main, "MIRROR_CADENCE_LOG_PATH", tmp_path / "mirror-cadence.jsonl")
