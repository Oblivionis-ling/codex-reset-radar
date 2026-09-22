from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .laya_worker import DecisionSettings


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
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 45.0
    deepseek_retries: int = 2
    judge_interval_seconds: int = 3600
    decision_settings: DecisionSettings | None = None


def _path(value: str, fallback: str) -> Path:
    candidate = Path(value or fallback)
    return candidate if candidate.is_absolute() else REPOSITORY_ROOT / candidate


def load_settings() -> Settings:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    from .laya_worker import DecisionSettings
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
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
        deepseek_timeout_seconds=max(5.0, float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "45"))),
        deepseek_retries=max(0, min(3, int(os.getenv("DEEPSEEK_RETRIES", "2")))),
        judge_interval_seconds=max(60, int(os.getenv("CRR_JUDGE_INTERVAL_SECONDS", "3600"))),
        decision_settings=DecisionSettings.from_environment(),
    )
