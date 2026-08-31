from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database(database_url: str, database_path: Path | None = None) -> tuple[Engine, sessionmaker]:
    if database_path:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args: dict[str, Any] = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)

    # Import models before create_all so every table is registered.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    migrate_legacy_schema(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, session_factory


def migrate_legacy_schema(engine: Engine) -> None:
    """Apply the small Phase B/C changes without deleting user data."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "classifications" not in tables and "alerts" not in tables:
        return

    with engine.begin() as connection:
        if "classifications" in tables:
            columns = {column["name"] for column in inspector.get_columns("classifications")}
            # Phase A used `classifier`; Phase B names the same audited field
            # `classifier_type`. SQLite supports this rename in current Python.
            if "classifier" in columns and "classifier_type" not in columns:
                connection.exec_driver_sql("ALTER TABLE classifications RENAME COLUMN classifier TO classifier_type")
                columns.remove("classifier")
                columns.add("classifier_type")
            additions = {
                "model_name": "VARCHAR(128)",
                "prompt_version": "VARCHAR(64)",
                "classification_conflict": "BOOLEAN NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.exec_driver_sql(f"ALTER TABLE classifications ADD COLUMN {name} {definition}")

        if "tweets" in tables:
            columns = {column["name"] for column in inspector.get_columns("tweets")}
            additions = {
                "translated_zh": "TEXT",
                "translation_model": "VARCHAR(128)",
                "translation_version": "VARCHAR(64)",
                "translated_at": "DATETIME",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.exec_driver_sql(f"ALTER TABLE tweets ADD COLUMN {name} {definition}")

        if "alerts" in tables:
            _migrate_alerts_table(connection, inspector)


def _migrate_alerts_table(connection, inspector) -> None:
    """Upgrade the Phase A alerts table while preserving existing rows."""
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if {"radar_state", "created_at"}.issubset(columns):
        return

    connection.exec_driver_sql(
        """
        CREATE TABLE alerts_new (
            id INTEGER PRIMARY KEY,
            tweet_id VARCHAR(64) NOT NULL,
            alert_type VARCHAR(32) NOT NULL,
            radar_state VARCHAR(16) NOT NULL DEFAULT 'unknown',
            channel VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL,
            sent_at DATETIME,
            error TEXT,
            CONSTRAINT uq_alert_dedup UNIQUE (alert_type, tweet_id, radar_state, channel)
        )
        """
    )
    radar_state_sql = "radar_state" if "radar_state" in columns else "'unknown'"
    created_at_sql = "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP"
    status_sql = "status" if "status" in columns else "'pending'"
    connection.exec_driver_sql(
        f"""
        INSERT INTO alerts_new (id, tweet_id, alert_type, radar_state, channel, status, created_at, sent_at, error)
        SELECT id, tweet_id, alert_type, {radar_state_sql}, channel, {status_sql}, {created_at_sql}, sent_at, error
        FROM alerts
        """
    )
    connection.exec_driver_sql("DROP TABLE alerts")
    connection.exec_driver_sql("ALTER TABLE alerts_new RENAME TO alerts")
