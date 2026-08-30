from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import Settings
from app.database import create_database
from app.intelligence.radar import update_radar
from app.models import Alert, Classification, MonitorHealth, NotificationBaseline, RadarState, Tweet
from app.notifications.alert_manager import AlertManager
from app.main import create_app


class RecordingNotifier:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def send(self, title: str, content: str) -> None:
        self.calls.append((title, content))


class FailingNotifier:
    def send(self, title: str, content: str) -> None:
        raise TimeoutError("mock timeout")


def make_settings(tmp_path, **overrides) -> Settings:
    values = {
        "database_path": tmp_path / "radar.db",
        "host": "127.0.0.1",
        "port": 8787,
        "deepseek_api_key": "",
        "deepseek_model": "deepseek-v4-flash",
        "deepseek_base_url": "https://api.deepseek.com",
        "prompt_version": "test",
        "alerts_enabled": True,
        "alert_dry_run": False,
        "wxpusher_enabled": True,
        "wxpusher_app_token": "test-token",
        "wxpusher_uid": "test-uid",
        "windows_notifications_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_radar_alerts_deduplicate_and_escalate(tmp_path):
    settings = make_settings(tmp_path)
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    wxpusher = RecordingNotifier()
    windows = RecordingNotifier()
    manager = AlertManager(settings, wxpusher=wxpusher, windows=windows, retry_delay=0)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(RadarState(id=1, state="QUIET", confidence=0, urgency="unknown", reason="baseline"))
        session.add(Tweet(tweet_id="hint-1", author="thsottiaux", text="soon", url="https://x.com/hint-1"))
        session.add(
            Classification(
                tweet_id="hint-1",
                classifier_type="final",
                category="reset_hint",
                confidence=0.80,
                urgency="unknown",
                explicitness="implicit",
                reason="First hint",
                created_at=now,
            )
        )
        session.commit()
        manager.initialize_baseline(session)
        session.commit()

        decision = update_radar(session, now)
        manager.handle_radar_transition(session, decision)
        session.commit()
        assert decision.state == "LIKELY"
        assert len(wxpusher.calls) == 1
        assert len(windows.calls) == 1
        assert session.query(Alert).count() == 2

        manager.handle_radar_transition(session, decision)
        session.commit()
        assert len(wxpusher.calls) == 1

        session.add(Tweet(tweet_id="hint-2", author="thsottiaux", text="tomorrow", url="https://x.com/hint-2"))
        session.add(
            Classification(
                tweet_id="hint-2",
                classifier_type="final",
                category="reset_hint",
                confidence=0.90,
                urgency="within_24h",
                explicitness="implicit",
                reason="Escalated hint",
                created_at=now + timedelta(seconds=1),
            )
        )
        session.commit()
        escalated = update_radar(session, now + timedelta(seconds=1))
        manager.handle_radar_transition(session, escalated)
        session.commit()
        assert escalated.state == "IMMINENT"
        assert len(wxpusher.calls) == 2
        assert "IMMINENT" in wxpusher.calls[-1][1]
    engine.dispose()


def test_startup_baseline_does_not_send_current_radar(tmp_path):
    settings = make_settings(tmp_path)
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    notifier = RecordingNotifier()
    manager = AlertManager(settings, wxpusher=notifier, windows=RecordingNotifier(), retry_delay=0)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(Tweet(tweet_id="confirmed", author="thsottiaux", text="reset confirmed", url="https://x.com/confirmed"))
        session.add(
            Classification(
                tweet_id="confirmed",
                classifier_type="final",
                category="reset_confirmed",
                confidence=0.99,
                urgency="now",
                explicitness="explicit",
                reason="Confirmed",
                created_at=now,
            )
        )
        session.commit()
        decision = update_radar(session, now)
        session.commit()
        manager.initialize_baseline(session)
        manager.handle_radar_transition(session, decision)
        session.commit()
        assert decision.state == "CONFIRMED"
        assert notifier.calls == []
    engine.dispose()


def test_new_confirmed_tweet_can_alert_against_historical_confirmed_baseline(tmp_path):
    settings = make_settings(tmp_path, windows_notifications_enabled=False)
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    notifier = RecordingNotifier()
    manager = AlertManager(settings, wxpusher=notifier, retry_delay=0)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(RadarState(id=1, state="CONFIRMED", confidence=0.99, urgency="now", reason="old"))
        session.add(
            Tweet(
                tweet_id="new-confirmed",
                author="thsottiaux",
                text="The reset has been propagated again.",
                url="https://x.com/new-confirmed",
            )
        )
        session.add(
            Classification(
                tweet_id="new-confirmed",
                classifier_type="final",
                category="reset_confirmed",
                confidence=0.98,
                urgency="now",
                explicitness="explicit",
                reason="New confirmed evidence",
                created_at=now,
            )
        )
        session.commit()
        manager.initialize_baseline(session)
        baseline = session.get(NotificationBaseline, 1)
        baseline.trigger_tweet_id = "old-confirmed"
        session.commit()
        decision = update_radar(session, now)
        manager.handle_radar_transition(session, decision)
        session.commit()
        assert decision.state == "CONFIRMED"
        assert len(notifier.calls) == 1
    engine.dispose()


def test_wxpusher_failure_is_recorded_without_escaping(tmp_path):
    settings = make_settings(tmp_path, windows_notifications_enabled=False)
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    manager = AlertManager(settings, wxpusher=FailingNotifier(), retry_attempts=3, retry_delay=0)
    with session_factory() as session:
        row = manager.send_test_alert(session, "wxpusher")
        session.commit()
        assert row is not None
        assert row.status == "failed"
        assert row.error == "mock timeout"
        assert session.query(type(row)).count() == 1
    engine.dispose()


def test_monitor_offline_and_recovery_are_debounced(tmp_path):
    settings = make_settings(tmp_path, windows_notifications_enabled=False)
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    notifier = RecordingNotifier()
    manager = AlertManager(settings, wxpusher=notifier, retry_delay=0)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        for component in ("profile_monitor", "replies_monitor", "search_backfill"):
            session.add(
                MonitorHealth(
                    component=component,
                    state="healthy",
                    last_heartbeat=now,
                    updated_at=now,
                )
            )
        session.commit()
        manager.initialize_baseline(session)
        session.commit()

        profile = session.get(MonitorHealth, "profile_monitor")
        profile.last_heartbeat = now - timedelta(minutes=31)
        session.commit()
        manager.evaluate_monitor_health(session, now=now)
        session.commit()
        assert len(notifier.calls) == 1
        assert "离线" in notifier.calls[0][1]

        manager.evaluate_monitor_health(session, now=now)
        session.commit()
        assert len(notifier.calls) == 1

        profile.last_heartbeat = now
        profile.state = "healthy"
        session.commit()
        manager.evaluate_monitor_health(session, now=now)
        session.commit()
        assert len(notifier.calls) == 2
        assert "恢复" in notifier.calls[1][1]
    engine.dispose()


def test_alert_api_is_local_and_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_DRY_RUN", "true")
    monkeypatch.setenv("WXPUSHER_ENABLED", "true")
    monkeypatch.setenv("WXPUSHER_APP_TOKEN", "not-a-real-token")
    monkeypatch.setenv("WXPUSHER_UID", "not-a-real-uid")
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", database_path=tmp_path / "api.db")
    with TestClient(app) as client:
        response = client.post("/api/alerts/test?channel=wxpusher")
        assert response.status_code == 200
        assert response.json()["status"] == "dry_run"
        alerts = client.get("/api/alerts").json()
        assert alerts[0]["alert_type"] == "test"
        assert alerts[0]["channel"] == "wxpusher"
    app.state.engine.dispose()


def test_legacy_alert_table_migrates_and_allows_channel_dedup(tmp_path):
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY,
                tweet_id VARCHAR(64) NOT NULL,
                alert_type VARCHAR(32) NOT NULL,
                channel VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'sent',
                sent_at DATETIME,
                error TEXT,
                CONSTRAINT uq_alert_tweet_type UNIQUE (tweet_id, alert_type)
            )
            """
        )
    legacy_engine.dispose()

    engine, session_factory = create_database(f"sqlite:///{database_path.as_posix()}", database_path)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(alerts)"))}
    assert {"radar_state", "created_at"}.issubset(columns)
    with session_factory() as session:
        session.add_all(
            [
                Alert(
                    tweet_id="same",
                    alert_type="reset_likely",
                    radar_state="LIKELY",
                    channel="wxpusher",
                    status="dry_run",
                ),
                Alert(
                    tweet_id="same",
                    alert_type="reset_likely",
                    radar_state="LIKELY",
                    channel="windows",
                    status="dry_run",
                ),
            ]
        )
        session.commit()
        assert session.query(Alert).count() == 2
    engine.dispose()
