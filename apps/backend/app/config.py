from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    log_dir: Path
    log_retention_days: int
    log_max_bytes: int
    cors_origins: tuple[str, ...]


def _path(value: str, fallback: str) -> Path:
    candidate = Path(value or fallback)
    return candidate if candidate.is_absolute() else REPOSITORY_ROOT / candidate


def load_settings() -> Settings:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "CRR_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip() and origin.strip() != "*"
    )
    return Settings(
        host=os.getenv("CRR_HOST", "127.0.0.1"),
        port=max(1, int(os.getenv("CRR_PORT", "8787"))),
        database_path=_path(
            os.getenv("CRR_DATABASE_PATH", ""),
            "runtime/data/codex-reset-radar-v2.db",
        ),
        log_dir=_path(os.getenv("CRR_LOG_DIR", ""), "runtime/logs"),
        log_retention_days=max(1, min(30, int(os.getenv("CRR_LOG_RETENTION_DAYS", "5")))),
        log_max_bytes=max(1_048_576, int(os.getenv("CRR_LOG_MAX_BYTES", "5242880"))),
        cors_origins=origins,
    )
