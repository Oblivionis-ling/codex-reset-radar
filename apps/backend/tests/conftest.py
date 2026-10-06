from __future__ import annotations

import os
import tempfile
from os import getpid
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings


def pytest_configure(config: pytest.Config) -> None:
    """Keep module-level app imports isolated in ordinary pytest/CI runs."""
    configured_basetemp = config.option.basetemp
    root = Path(configured_basetemp).resolve() if configured_basetemp else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    # Never inherit a caller's database override into pytest's module-level
    # `app.main` import. Tests needing a database receive one under tmp_path.
    safe_path = root / f"crr-pytest-import-guard-{getpid()}-{uuid4().hex}.sqlite"
    os.environ["CRR_DATABASE_PATH"] = str(safe_path)


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
    from app.main import create_app

    with TestClient(create_app(settings)) as current:
        yield current
