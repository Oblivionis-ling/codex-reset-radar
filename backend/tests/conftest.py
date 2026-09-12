from __future__ import annotations

import pytest

import app.main as backend_main
import app.notifications.alert_manager as alert_manager
import app.observability as observability


@pytest.fixture(autouse=True)
def disable_live_github_mirror_for_tests(monkeypatch, tmp_path):
    """Keep TestClient suites offline; mirror behavior has dedicated unit coverage."""

    events_dir = tmp_path / "observability" / "events"
    runtime_dir = tmp_path / "observability" / "runtime"
    monkeypatch.setattr(observability, "OBSERVABILITY_DIR", tmp_path / "observability")
    monkeypatch.setattr(observability, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(observability, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(observability, "RUNTIME_LOG_PATH", runtime_dir / "backend-runtime.log")
    monkeypatch.setattr(observability, "BACKEND_EVENTS_PATH", events_dir / "backend.jsonl")
    monkeypatch.setattr(backend_main, "BACKEND_EVENTS_PATH", events_dir / "backend.jsonl")
    monkeypatch.setattr(backend_main, "EVENTS_DIR", events_dir)
    monkeypatch.setattr(backend_main, "RUNTIME_LOG_PATH", runtime_dir / "backend-runtime.log")
    monkeypatch.setattr(alert_manager, "NOTIFICATION_DIAGNOSTIC_LOG_PATH", tmp_path / "notification-delivery.jsonl")
    monkeypatch.setattr(alert_manager, "NOTIFICATION_TEST_LOG_PATH", tmp_path / "notification-test.jsonl")
    monkeypatch.setattr(backend_main, "NOTIFICATION_DIAGNOSTIC_LOG_PATH", tmp_path / "notification-delivery.jsonl")
    monkeypatch.setattr(backend_main, "NOTIFICATION_TEST_LOG_PATH", tmp_path / "notification-test.jsonl")

    # app.main is imported before pytest fixtures run and configures a runtime
    # handler using the real data directory. Remove that handler and recreate
    # it against the per-test directory so regression tests never contaminate
    # the operator's production logs.
    root_logger = __import__("logging").getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, "_radar_runtime", False):
            root_logger.removeHandler(handler)
            handler.close()
    monkeypatch.setattr(observability, "_LOGGING_CONFIGURED", False)
    observability.configure_runtime_logging()

    monkeypatch.setenv("GITHUB_MIRROR_ENABLED", "false")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(backend_main, "MIRROR_CADENCE_LOG_PATH", tmp_path / "mirror-cadence.jsonl")
