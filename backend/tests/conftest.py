from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_live_github_mirror_for_tests(monkeypatch):
    """Keep TestClient suites offline; mirror behavior has dedicated unit coverage."""

    monkeypatch.setenv("GITHUB_MIRROR_ENABLED", "false")
