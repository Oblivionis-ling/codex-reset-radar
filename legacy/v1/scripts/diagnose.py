#!/usr/bin/env python3
"""Local read-only diagnostic CLI for Codex Reset Radar.

This intentionally uses only the standard library so it can still inspect a
broken Backend installation without importing the application itself.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "backend" / "data" / "radar.db"
OBS_DIR = ROOT / "backend" / "data" / "observability"
EVENT_DIR = OBS_DIR / "events"
MAX_CLI_LIMIT = 500

# The application module owns the single bounded-tail implementation. Import
# only that stdlib-only module so this CLI remains usable while the FastAPI
# process itself is unhealthy.
sys.path.insert(0, str(ROOT / "backend"))
from app.observability import read_all_events as _read_all_events  # noqa: E402
from app.observability import read_events as _read_stream_events  # noqa: E402


def parse_time(value: Any) -> datetime | None:
    if not value or value == "-":
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def time_text(value: Any) -> str:
    parsed = parse_time(value)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if parsed else str(value or "unknown")


def observability_since(value: str | None, *, default: timedelta = timedelta(hours=24)) -> datetime:
    current = datetime.now(timezone.utc)
    if not value:
        return current - default
    parsed = parse_time(value)
    if parsed is None:
        raise ValueError("since must be an ISO-8601 timestamp")
    parsed = parsed.astimezone(timezone.utc)
    if parsed < current - timedelta(days=14):
        raise ValueError("since exceeds the 14-day observability window")
    return parsed


def sqlite_time(value: datetime) -> str:
    """Match SQLite's SQLAlchemy DateTime text representation."""

    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def read_events(limit_per_stream: int = MAX_CLI_LIMIT, *, since: datetime | None = None) -> list[dict[str, Any]]:
    """Read a bounded recent view through the Backend's shared abstraction."""

    return _read_all_events(
        min(max(1, int(limit_per_stream)), MAX_CLI_LIMIT),
        since=since,
    )


def read_stream_events(stream: str, limit: int = MAX_CLI_LIMIT, *, since: datetime | None = None) -> list[dict[str, Any]]:
    return _read_stream_events(
        stream,
        min(max(1, int(limit)), MAX_CLI_LIMIT),
        since=since,
    )


def live_backend_health() -> dict[str, Any] | None:
    """Read the live local health response without importing the Backend."""

    try:
        request = Request("http://127.0.0.1:8787/health", headers={"Accept": "application/json"})
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None


def live_backend_instance_id() -> str | None:
    """Prefer the instance exposed by the live local process over stale JSONL starts."""

    payload = live_backend_health()
    value = payload.get("backend_instance_id") if payload else None
    return str(value) if value else None


def event_matches_backend(event: dict[str, Any], instance_id: str | None) -> bool:
    if not instance_id:
        return True
    if event.get("instance_id") == instance_id or event.get("backend_instance_id") == instance_id:
        return True
    metadata = event.get("metadata")
    return isinstance(metadata, dict) and metadata.get("backend_instance_id") == instance_id


def event_matches_component(event: dict[str, Any], component: str) -> bool:
    if event.get("component") == component:
        return True
    metadata = event.get("metadata")
    return isinstance(metadata, dict) and metadata.get("component") == component


def event_matches_instance(event: dict[str, Any], instance_id: str | None) -> bool:
    if not instance_id:
        return True
    if event.get("instance_id") == instance_id:
        return True
    metadata = event.get("metadata")
    if isinstance(metadata, dict) and (
        metadata.get("instance_id") == instance_id
        or metadata.get("content_instance_id") == instance_id
        or metadata.get("service_worker_instance_id") == instance_id
        or metadata.get("extension_instance_id") == instance_id
    ):
        return True
    return False


def event_matches_trace(event: dict[str, Any], trace_id: str | None) -> bool:
    if not trace_id:
        return True
    if event.get("trace_id") == trace_id:
        return True
    metadata = event.get("metadata")
    return isinstance(metadata, dict) and metadata.get("trace_id") == trace_id


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def has_table(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def current_health(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    if not has_table(connection, "monitor_health"):
        return []
    return connection.execute("SELECT * FROM monitor_health ORDER BY component").fetchall()


def derived_health_state(row: sqlite3.Row, now: datetime | None = None) -> str:
    if row["state"] == "offline":
        return "offline"
    heartbeat = parse_time(row["last_heartbeat"])
    if heartbeat is None:
        return "unknown"
    age_seconds = max(0.0, ((now or datetime.now(timezone.utc)) - heartbeat).total_seconds())
    if age_seconds > 30 * 60:
        return "offline"
    if age_seconds > 15 * 60 and row["state"] == "healthy":
        return "warning"
    return str(row["state"])


def latest_heartbeat_interval(connection: sqlite3.Connection, component: str) -> float | None:
    if not has_table(connection, "heartbeat_history"):
        return None
    rows = connection.execute(
        "SELECT backend_received_at FROM heartbeat_history WHERE component=? ORDER BY id DESC LIMIT 2",
        (component,),
    ).fetchall()
    if len(rows) < 2:
        return None
    newer = parse_time(rows[0]["backend_received_at"])
    older = parse_time(rows[1]["backend_received_at"])
    return (newer - older).total_seconds() if newer and older else None


def event_name(event: dict[str, Any]) -> str:
    return str(event.get("event") or "UNKNOWN")


def print_event(event: dict[str, Any]) -> None:
    fields = [time_text(event.get("timestamp") or event.get("logged_at")), event_name(event), str(event.get("component") or "-")]
    if event.get("origin"):
        fields.append(f"origin={event['origin']}")
    if event.get("sequence") is not None:
        fields.append(f"seq={event['sequence']}")
    if event.get("trace_id"):
        fields.append(f"trace={event['trace_id']}")
    if event.get("request_id"):
        fields.append(f"request={event['request_id']}")
    if event.get("error_type"):
        fields.append(f"error_type={event['error_type']}")
    if event.get("error"):
        fields.append(f"error={event['error']}")
    if event.get("client_observed_at"):
        fields.append(f"client={time_text(event['client_observed_at'])}")
    if event.get("backend_received_at"):
        fields.append(f"received={time_text(event['backend_received_at'])}")
    if event.get("db_committed_at"):
        fields.append(f"committed={time_text(event['db_committed_at'])}")
    if event.get("created_at"):
        fields.append(f"created={time_text(event['created_at'])}")
    print(" | ".join(fields))


def command_summary(connection: sqlite3.Connection, since: datetime | None = None) -> int:
    events = read_events(since=since)
    active_instance = live_backend_instance_id()
    starts = [event for event in events if event_name(event) == "BACKEND_PROCESS_STARTED"]
    if active_instance:
        starts = [event for event in starts if event.get("instance_id") == active_instance]
    latest_start = starts[-1] if starts else None
    ready = next(
        (
            event
            for event in reversed(events)
            if event_name(event) == "BACKEND_READY"
            and (not active_instance or event_matches_backend(event, active_instance))
        ),
        None,
    )
    print("BACKEND")
    print(f"  Instance: {active_instance or 'unknown (live /health has no backend_instance_id)'}")
    start_label = "Started" if active_instance else "Last recorded STARTED"
    print(f"  {start_label}: {time_text(latest_start.get('timestamp')) if latest_start else 'unknown'}")
    if active_instance and latest_start and parse_time(latest_start.get("timestamp")):
        print(f"  Uptime: {(datetime.now(timezone.utc) - parse_time(latest_start['timestamp'])).total_seconds():.0f}s")
    print(f"  Ready: {ready.get('result') if ready and active_instance else 'unknown (live process identity unavailable)'}")
    lag = next(
        (
            event
            for event in reversed(events)
            if event_name(event) == "EVENT_LOOP_LAG_DETECTED"
            and (not active_instance or event_matches_backend(event, active_instance))
        ),
        None,
    )
    print(f"  Event loop: {lag.get('lag_ms')}ms lag at {time_text(lag.get('timestamp'))}" if lag else "  Event loop: no lag event recorded")
    print("  Tasks:")
    if not active_instance:
        print("    unknown (restart to load Phase H observability identity)")
    latest_tasks: dict[str, dict[str, Any]] = {}
    for event in events:
        if event_name(event).startswith("TASK_") and event.get("task_name") and event_matches_backend(event, active_instance):
            latest_tasks[str(event["task_name"])] = event
    if active_instance:
        for name, event in latest_tasks.items():
            print(f"    {name}: {event_name(event).removeprefix('TASK_').lower()}")
    print("COMPONENTS")
    for row in current_health(connection):
        age = max(0.0, (datetime.now(timezone.utc) - (parse_time(row["last_heartbeat"]) or datetime.now(timezone.utc))).total_seconds())
        interval = latest_heartbeat_interval(connection, str(row["component"]))
        interval_text = f" interval={interval:.1f}s" if interval is not None else ""
        print(
            f"  {row['component']}: {derived_health_state(row)} (reported={row['state']}) "
            f"last={time_text(row['last_heartbeat'])} age={age:.1f}s{interval_text} error={row['last_error'] or '-'}"
        )
    mirror = [event for event in events if event_name(event) in {"PUBLIC_MIRROR_SYNC_SUCCESS", "PUBLIC_MIRROR_SYNC_FAILED"} and event_matches_backend(event, active_instance)]
    notification = [event for event in events if event_name(event) in {"WXPUSHER_REQUEST_SUCCESS", "WXPUSHER_REQUEST_FAILED"} and event_matches_backend(event, active_instance)]
    print(f"MIRROR: {event_name(mirror[-1]) if mirror else 'no event'} at {time_text(mirror[-1].get('timestamp')) if mirror else 'unknown'}")
    print(f"WXPUSHER: {event_name(notification[-1]) if notification else 'no event'} at {time_text(notification[-1].get('timestamp')) if notification else 'unknown'}")
    return 0


def normalise_component(value: str) -> str:
    return {"profile": "profile_monitor", "replies": "replies_monitor", "search": "search_backfill"}.get(value, value)


def command_component(
    connection: sqlite3.Connection,
    component: str,
    limit: int,
    instance_id: str | None = None,
    trace_id: str | None = None,
    since: datetime | None = None,
) -> int:
    component = normalise_component(component)
    filters = []
    if instance_id:
        filters.append(f"instance_id={instance_id}")
    if trace_id:
        filters.append(f"trace_id={trace_id}")
    since = since or observability_since(None)
    filters.append(f"since={time_text(since)}")
    print(f"COMPONENT {component}" + (f" ({', '.join(filters)})" if filters else ""))
    health = connection.execute("SELECT * FROM monitor_health WHERE component=?", (component,)).fetchone() if has_table(connection, "monitor_health") else None
    if health:
        age = max(0.0, (datetime.now(timezone.utc) - (parse_time(health["last_heartbeat"]) or datetime.now(timezone.utc))).total_seconds())
        interval = latest_heartbeat_interval(connection, component)
        interval_text = f"  actual interval: {interval:.1f}s" if interval is not None else "  actual interval: unknown"
        print(
            f"  State: {derived_health_state(health)} (reported={health['state']})  "
            f"last heartbeat: {time_text(health['last_heartbeat'])}  age: {age:.1f}s\n{interval_text}  "
            f"error: {health['last_error'] or '-'}"
        )
    else:
        print("  State: unknown (no monitor_health row)")
    if has_table(connection, "heartbeat_history"):
        query = "SELECT * FROM heartbeat_history WHERE component=? AND backend_received_at>=?"
        params: list[Any] = [component, sqlite_time(since)]
        if instance_id:
            query += " AND instance_id=?"
            params.append(instance_id)
        if trace_id:
            query += " AND trace_id=?"
            params.append(trace_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, params).fetchall()
        print("  Heartbeats:")
        for row in reversed(rows):
            print(
                f"    received={time_text(row['backend_received_at'])} "
                f"client={time_text(row['client_observed_at'])} "
                f"committed={time_text(row['db_committed_at'])} "
                f"seq={row['sequence'] or '-'} instance={row['instance_id'] or '-'} "
                f"trace={row['trace_id'] or '-'} state={row['state']}"
            )
    if has_table(connection, "health_state_history"):
        query = "SELECT * FROM health_state_history WHERE component=? AND changed_at>=?"
        params = [component, sqlite_time(since)]
        if instance_id:
            query += " AND instance_id=?"
            params.append(instance_id)
        if trace_id:
            query += " AND trace_id=?"
            params.append(trace_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, params).fetchall()
        print("  Health transitions:")
        for row in reversed(rows):
            print(f"    {time_text(row['changed_at'])} {row['previous_state'] or 'unknown'} -> {row['new_state']} age={row['heartbeat_age_seconds']}")
    print("  Timeline (Extension diagnostic / Backend event / SQLite commit):")
    active_instance = live_backend_instance_id()
    if not active_instance:
        print("  Note: live Backend instance_id is unavailable; JSONL Backend events are shown without claiming current process ownership.")
    timeline: list[dict[str, Any]] = []
    for event in read_events(since=since):
        if (
            event_matches_component(event, component)
            and (instance_id or event_matches_backend(event, active_instance))
            and event_matches_instance(event, instance_id)
            and event_matches_trace(event, trace_id)
        ):
            timeline.append({**event, "origin": "backend-jsonl"})

    if has_table(connection, "monitor_diagnostic_events"):
        diagnostic_query = "SELECT * FROM monitor_diagnostic_events WHERE component=? AND created_at>=?"
        diagnostic_params: list[Any] = [component, sqlite_time(since)]
        if instance_id:
            diagnostic_query += " AND details_json LIKE ?"
            diagnostic_params.append(f"%{instance_id}%")
        if trace_id:
            diagnostic_query += " AND details_json LIKE ?"
            diagnostic_params.append(f"%{trace_id}%")
        diagnostic_query += " ORDER BY id DESC LIMIT ?"
        diagnostic_params.append(max(limit * 20, 200))
        diagnostic_rows = connection.execute(diagnostic_query, diagnostic_params).fetchall()
        for row in diagnostic_rows:
            try:
                details = json.loads(row["details_json"] or "{}")
            except json.JSONDecodeError:
                details = {}
            candidate = {
                "timestamp": row["observed_at"],
                "event": row["event"],
                "component": row["component"],
                "sequence": details.get("sequence"),
                "trace_id": details.get("trace_id"),
                "request_id": details.get("request_id"),
                "instance_id": details.get("instance_id") or details.get("content_instance_id") or details.get("service_worker_instance_id"),
                "created_at": row["created_at"],
                "origin": "diagnostic-db",
            }
            if event_matches_instance(candidate, instance_id) and event_matches_trace(candidate, trace_id):
                timeline.append(candidate)

    if has_table(connection, "heartbeat_history"):
        query = "SELECT * FROM heartbeat_history WHERE component=? AND backend_received_at>=?"
        params = [component, sqlite_time(since)]
        if instance_id:
            query += " AND instance_id=?"
            params.append(instance_id)
        if trace_id:
            query += " AND trace_id=?"
            params.append(trace_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(limit * 5, 50))
        for row in connection.execute(query, params).fetchall():
            timeline.append(
                {
                    "timestamp": row["db_committed_at"] or row["backend_received_at"],
                    "event": "HEARTBEAT_DB_COMMITTED",
                    "component": row["component"],
                    "sequence": row["sequence"],
                    "trace_id": row["trace_id"],
                    "request_id": row["request_id"],
                    "instance_id": row["instance_id"],
                    "client_observed_at": row["client_observed_at"],
                    "backend_received_at": row["backend_received_at"],
                    "db_committed_at": row["db_committed_at"],
                    "origin": "sqlite-commit",
                }
            )

    timeline.sort(key=lambda event: str(event.get("timestamp") or event.get("logged_at") or ""))
    for event in timeline[-limit:]:
        print_event(event)
    return 0


def command_trace(
    connection: sqlite3.Connection,
    trace_id: str,
    limit: int,
    since: datetime | None = None,
) -> int:
    since = since or observability_since(None)
    records = [
        event
        for event in _read_all_events(
            min(max(limit * 2, 20), MAX_CLI_LIMIT),
            trace_id=trace_id,
            since=since,
        )
    ]
    if has_table(connection, "heartbeat_history"):
        rows = connection.execute(
            "SELECT * FROM heartbeat_history "
            "WHERE trace_id=? AND backend_received_at>=? "
            "ORDER BY id DESC LIMIT ?",
            (trace_id, sqlite_time(since), limit),
        ).fetchall()
        for row in reversed(rows):
            records.append({"timestamp": row["backend_received_at"], "event": "HEARTBEAT_DB_COMMITTED", "component": row["component"], "trace_id": trace_id, "sequence": row["sequence"], "request_id": row["request_id"], "result": "success"})
    if has_table(connection, "monitor_diagnostic_events"):
        rows = connection.execute(
            "SELECT * FROM monitor_diagnostic_events "
            "WHERE created_at>=? AND details_json LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (sqlite_time(since), f"%{trace_id}%", limit),
        ).fetchall()
        for row in reversed(rows):
            try:
                details = json.loads(row["details_json"] or "{}")
            except json.JSONDecodeError:
                details = {}
            if details.get("trace_id") == trace_id:
                records.append({"timestamp": row["observed_at"], "event": row["event"], "component": row["component"], "trace_id": trace_id, "sequence": details.get("sequence"), "request_id": details.get("request_id")})
    records.sort(key=lambda item: str(item.get("timestamp") or ""))
    print(f"TRACE {trace_id}")
    if not records:
        print("  no records")
        return 1
    for event in records[-limit:]:
        print_event(event)
    return 0


def command_outage(connection: sqlite3.Connection, component: str) -> int:
    component = normalise_component(component)
    print(f"OUTAGE {component}")
    if not has_table(connection, "health_state_history"):
        print("  health_state_history is not available")
        return 1
    since = observability_since(None, default=timedelta(days=14))
    rows = connection.execute(
        "SELECT * FROM health_state_history "
        "WHERE component=? AND changed_at>=? ORDER BY id ASC LIMIT ?",
        (component, sqlite_time(since), MAX_CLI_LIMIT),
    ).fetchall()
    start: sqlite3.Row | None = None
    end: sqlite3.Row | None = None
    for row in rows:
        if row["new_state"] == "offline":
            start, end = row, None
        elif start and row["new_state"] == "healthy":
            end = row
    if not start:
        print("  no offline transition recorded")
        return 0
    started = parse_time(start["changed_at"])
    recovered = parse_time(end["changed_at"]) if end else None
    duration = ((recovered or datetime.now(timezone.utc)) - started).total_seconds() if started else None
    print(f"  Started: {time_text(start['changed_at'])}")
    print(f"  Recovered: {time_text(end['changed_at']) if end else 'still open'}")
    print(f"  Duration: {duration:.0f}s" if duration is not None else "  Duration: unknown")
    print(f"  Reason: {start['reason']}")
    command_component(connection, component, 20, since=since)
    return 0


def command_backend(connection: sqlite3.Connection, since: datetime | None = None) -> int:
    events = read_events(since=since)
    active_instance = live_backend_instance_id()
    print("BACKEND DETAIL")
    if not active_instance:
        print("  Live Backend instance_id unavailable; showing recorded lifecycle events without claiming current ownership.")
    for event in events:
        if event_name(event) in {"BACKEND_PROCESS_STARTED", "PREVIOUS_BACKEND_INSTANCE_UNCLEAN_EXIT", "BACKEND_SHUTDOWN_STARTED", "BACKEND_SHUTDOWN_COMPLETED", "TASK_FAILED", "EVENT_LOOP_LAG_DETECTED", "BACKEND_HEARTBEAT_DB_WRITE_FAILED", "SQLITE_LOCK_DETECTED"} and event_matches_backend(event, active_instance):
            print_event(event)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex Reset Radar observability diagnostics")
    parser.add_argument("command", choices=("summary", "component", "trace", "outage", "backend"))
    parser.add_argument("value", nargs="?")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--instance-id", dest="instance_id")
    parser.add_argument("--trace-id", dest="trace_id")
    parser.add_argument("--since", help="ISO-8601 lower bound; maximum lookback is 14 days")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2
    connection = connect(args.db)
    try:
        try:
            since = observability_since(args.since)
        except ValueError as exc:
            parser.error(str(exc))
        if args.command == "summary":
            return command_summary(connection, since=since)
        if args.command == "backend":
            return command_backend(connection, since=since)
        if not args.value:
            parser.error(f"{args.command} requires a value")
        if args.command == "component":
            return command_component(
                connection,
                args.value,
                max(1, min(args.limit, 500)),
                instance_id=args.instance_id,
                trace_id=args.trace_id,
                since=since,
            )
        if args.command == "trace":
            return command_trace(connection, args.value, max(1, min(args.limit, MAX_CLI_LIMIT)), since=since)
        return command_outage(connection, args.value)
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
