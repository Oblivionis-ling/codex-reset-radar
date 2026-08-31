from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - only used before dependencies are installed
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_path: Path
    host: str
    port: int
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str
    prompt_version: str
    translation_version: str = "tibo-translation-v1"
    alerts_enabled: bool = True
    alert_dry_run: bool = False
    wxpusher_enabled: bool = False
    wxpusher_app_token: str = ""
    wxpusher_uid: str = ""
    windows_notifications_enabled: bool = False
    github_mirror_enabled: bool = True
    github_mirror_interval_seconds: int = 300

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


def get_settings() -> Settings:
    configured_path = os.getenv("RADAR_DB_PATH", "backend/data/radar.db")
    database_path = Path(configured_path)
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return Settings(
        database_path=database_path,
        host=os.getenv("RADAR_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("RADAR_BACKEND_PORT", "8787")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash",
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        prompt_version=os.getenv("DEEPSEEK_PROMPT_VERSION", "tibo-classifier-v1").strip() or "tibo-classifier-v1",
        translation_version=os.getenv("DEEPSEEK_TRANSLATION_VERSION", "tibo-translation-v1").strip() or "tibo-translation-v1",
        alerts_enabled=_env_bool("ALERTS_ENABLED", True),
        alert_dry_run=_env_bool("ALERT_DRY_RUN", False),
        wxpusher_enabled=_env_bool("WXPUSHER_ENABLED", False),
        wxpusher_app_token=os.getenv("WXPUSHER_APP_TOKEN", "").strip(),
        wxpusher_uid=os.getenv("WXPUSHER_UID", "").strip(),
        windows_notifications_enabled=_env_bool("WINDOWS_NOTIFICATIONS_ENABLED", False),
        github_mirror_enabled=_env_bool("GITHUB_MIRROR_ENABLED", True),
        github_mirror_interval_seconds=max(60, int(os.getenv("GITHUB_MIRROR_INTERVAL_SECONDS", "300"))),
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
