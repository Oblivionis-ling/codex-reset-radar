from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8787,
        database_path=tmp_path / "v2-test.db",
        log_dir=tmp_path / "logs",
        log_retention_days=5,
        log_max_bytes=1_048_576,
        cors_origins=("http://127.0.0.1:5173",),
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as current:
        yield current
