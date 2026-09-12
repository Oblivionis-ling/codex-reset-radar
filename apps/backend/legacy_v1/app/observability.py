"""Local-first observability primitives shared by the Radar subsystems.

The module deliberately has no dependency on FastAPI or the ORM.  It owns
the common event envelope, safe JSONL writes, the Backend runtime handler,
process identity, task supervision, and the lightweight event-loop watchdog.
"""

from __future__ import annotations

import atexit
import asyncio
import contextvars
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Collection, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OBSERVABILITY_DIR = PROJECT_ROOT / "backend" / "data" / "observability"
OBSERVABILITY_DIR = Path(os.getenv("RADAR_OBSERVABILITY_DIR", str(DEFAULT_OBSERVABILITY_DIR)))
RUNTIME_DIR = OBSERVABILITY_DIR / "runtime"
EVENTS_DIR = OBSERVABILITY_DIR / "events"
RUNTIME_LOG_PATH = RUNTIME_DIR / "backend-runtime.log"
BACKEND_EVENTS_PATH = EVENTS_DIR / "backend.jsonl"
EVENT_SHARD_RE = re.compile(r"^(?P<stream>[a-z0-9_-]+)-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")
EVENT_STREAMS = ("backend", "mirror", "notifications")
DEFAULT_EVENT_TAIL_LIMIT = 5000
DEFAULT_EVENT_BLOCK_SIZE = 64 * 1024

_WRITE_LOCK = threading.RLock()
_LOGGING_CONFIGURED = False
_PROCESS_STARTED = False
_PROCESS_SHUTDOWN_RECORDED = False
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)
_TRACE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("radar_trace_id", default=None)
_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("radar_request_id", default=None)
_ENVIRONMENT: contextvars.ContextVar[str] = contextvars.ContextVar("radar_environment", default="production")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def new_backend_instance_id() -> str:
    return f"backend-{utc_iso().replace('-', '').replace(':', '').replace('.', '')[:15]}-{uuid.uuid4().hex[:6]}"


BACKEND_INSTANCE_ID = new_backend_instance_id()
PROCESS_STARTED_AT = utc_now()


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def current_environment() -> str:
    return _ENVIRONMENT.get()


@contextmanager
def observability_context(*, trace_id: str | None = None, request_id: str | None = None, environment: str | None = None) -> Iterator[None]:
    trace_token = _TRACE_ID.set(trace_id if trace_id is not None else _TRACE_ID.get())
    request_token = _REQUEST_ID.set(request_id if request_id is not None else _REQUEST_ID.get())
    environment_token = _ENVIRONMENT.set(environment if environment is not None else _ENVIRONMENT.get())
    try:
        yield
    finally:
        _TRACE_ID.reset(trace_token)
        _REQUEST_ID.reset(request_token)
        _ENVIRONMENT.reset(environment_token)


def _secret_values() -> tuple[str, ...]:
    names = (
        "GITHUB_TOKEN",
        "DEEPSEEK_API_KEY",
        "WXPUSHER_APP_TOKEN",
        "WXPUSHER_UID",
        "RADAR_AUTHORIZATION",
    )
    return tuple(value for name in names if (value := os.getenv(name, "").strip()))


def redact_secret(value: Any) -> str:
    """Return bounded text with configured credentials and auth material removed."""

    text = " ".join(str(value or "").split())
    for secret in _secret_values():
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(cookie\s*[:=]\s*)[^\s]+", r"\1[redacted]", text)
    text = re.sub(r"(https?://)([^/\s:@]+):([^@\s]+)@", r"\1[redacted]@", text)
    return text[:2000]


def is_sqlite_lock_error(value: Any) -> bool:
    """Identify SQLite lock failures without asserting which peer caused them."""

    text = redact_secret(value).lower()
    return "database is locked" in text or "database table is locked" in text


def _safe_value(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(token in lowered for token in ("token", "secret", "password", "authorization", "cookie", "credential")):
        return "[redacted]" if value not in (None, "") else value
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, str):
        return redact_secret(value)
    if isinstance(value, dict):
        return {str(child_key): _safe_value(child_value, key=str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(child, key=key) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return redact_secret(value)


def _normalise_time_fields(record: dict[str, Any]) -> dict[str, Any]:
    time_keys = {
        "timestamp", "observed_at", "received_at", "started_at", "finished_at", "published_at",
        "generated_at", "created_at", "updated_at", "cycle_started_at", "snapshot_generated_at",
        "push_started_at", "sync_finished_at", "mirror_synced_at", "previous_success_at",
        "client_observed_at", "backend_received_at", "db_committed_at", "last_heartbeat_at",
        "outage_started_at", "recovered_at",
    }
    for key, value in list(record.items()):
        if key not in time_keys or not isinstance(value, str) or value in {"", "-"}:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        record[key] = utc_iso(parsed)
    return record


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _parse_event_time(value: Any) -> datetime | None:
    if not value or value == "-":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _event_path(stream: str, timestamp: str) -> Path:
    parsed = _parse_event_time(timestamp) or utc_now()
    return EVENTS_DIR / f"{stream}-{parsed.astimezone(timezone.utc).date().isoformat()}.jsonl"


def archive_legacy_event_file(path: Path | None = None, *, now: datetime | None = None) -> Path | None:
    """Move the pre-H single-file stream aside without parsing or deleting it."""

    path = path or BACKEND_EVENTS_PATH
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        stamp = (now or utc_now()).astimezone(timezone.utc).date().isoformat()
        target = path.with_name(f"backend-events-legacy-{stamp}.jsonl")
        if target.exists():
            target = path.with_name(f"backend-events-legacy-{stamp}-{uuid.uuid4().hex[:8]}.jsonl")
        path.replace(target)
        return target
    except OSError:
        return None


def append_event(
    stream: str,
    event: str,
    *,
    level: str = "INFO",
    component: str = "backend",
    timestamp: datetime | str | None = None,
    instance_id: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    sequence: int | None = None,
    duration_ms: int | float | None = None,
    result: str | None = None,
    error_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    legacy_paths: tuple[Path, ...] = (),
    **fields: Any,
) -> dict[str, Any]:
    """Write one safe event to the unified stream and optional compatibility files."""

    if isinstance(timestamp, datetime):
        event_timestamp = utc_iso(timestamp)
    elif isinstance(timestamp, str) and timestamp not in {"", "-"}:
        try:
            event_timestamp = utc_iso(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
        except ValueError:
            event_timestamp = redact_secret(timestamp)
    else:
        event_timestamp = utc_iso()
    record: dict[str, Any] = {
        "timestamp": event_timestamp,
        "event": event,
        "level": level,
        "component": component,
        "instance_id": instance_id or BACKEND_INSTANCE_ID,
        "trace_id": trace_id if trace_id is not None else current_trace_id(),
        "request_id": request_id if request_id is not None else current_request_id(),
        "sequence": sequence,
        "duration_ms": duration_ms,
        "result": result,
        "error_type": error_type,
        "metadata": metadata or {},
        # Compatibility with the existing event files and operators.
        "logged_at": event_timestamp,
    }
    record.update(fields)
    record = {key: _safe_value(value, key=key) for key, value in record.items()}
    legacy_record = dict(record)
    _normalise_time_fields(record)
    try:
        _write_jsonl(_event_path(stream, event_timestamp), record)
        for legacy_path in legacy_paths:
            _write_jsonl(legacy_path, legacy_record)
    except OSError as exc:
        # Observability must not take down collection or notifications.
        logging.getLogger("radar.observability").error(
            "OBSERVABILITY_WRITE_FAILED stream=%s event=%s error=%s", stream, event, redact_secret(exc)
        )
    return record


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.instance_id = getattr(record, "instance_id", BACKEND_INSTANCE_ID)
        try:
            record.msg = redact_secret(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def configure_runtime_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s instance_id=%(instance_id)s - %(message)s")
    for handler in root.handlers:
        handler.addFilter(RedactingFilter())
    if not any(getattr(handler, "_radar_console", False) for handler in root.handlers):
        console = logging.StreamHandler()
        console._radar_console = True  # type: ignore[attr-defined]
        console.setFormatter(formatter)
        console.addFilter(RedactingFilter())
        root.addHandler(console)
    if not any(getattr(handler, "_radar_runtime", False) for handler in root.handlers):
        runtime = TimedRotatingFileHandler(
            RUNTIME_LOG_PATH,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=True,
        )
        runtime._radar_runtime = True  # type: ignore[attr-defined]
        runtime.setFormatter(formatter)
        runtime.addFilter(RedactingFilter())
        root.addHandler(runtime)
    _LOGGING_CONFIGURED = True


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def _event_matches(
    record: dict[str, Any],
    *,
    event_filter: str | Collection[str] | None = None,
    component_filter: str | Collection[str] | None = None,
    trace_id: str | None = None,
    since: datetime | None = None,
) -> bool:
    def matches(value: Any, expected: str | Collection[str] | None) -> bool:
        if expected is None:
            return True
        if isinstance(expected, str):
            return value == expected
        return value in expected

    if not matches(record.get("event"), event_filter):
        return False
    if not matches(record.get("component"), component_filter):
        return False
    if trace_id is not None:
        metadata = record.get("metadata")
        if record.get("trace_id") != trace_id and not (isinstance(metadata, dict) and metadata.get("trace_id") == trace_id):
            return False
    if since is not None:
        timestamp = _parse_event_time(record.get("timestamp") or record.get("logged_at"))
        if timestamp is not None and timestamp < since:
            return False
    return True


def tail_jsonl(
    path: Path,
    limit: int = DEFAULT_EVENT_TAIL_LIMIT,
    *,
    event_filter: str | Collection[str] | None = None,
    component_filter: str | Collection[str] | None = None,
    trace_id: str | None = None,
    since: datetime | str | None = None,
    block_size: int = DEFAULT_EVENT_BLOCK_SIZE,
    max_scan_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Read the tail of a JSONL file without loading the full file into memory."""

    limit = max(0, min(int(limit), 10000))
    if limit == 0 or not path.exists():
        return []
    since_time = _parse_event_time(since)
    block_size = max(4096, min(int(block_size), 4 * 1024 * 1024))
    matches: list[dict[str, Any]] = []

    def decode(raw: bytes) -> dict[str, Any] | None:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            scan_floor = max(0, position - int(max_scan_bytes)) if max_scan_bytes else 0
            remainder = b""
            stop_at_since = False
            while position > scan_floor and len(matches) < limit and not stop_at_since:
                size = min(block_size, position - scan_floor)
                position -= size
                handle.seek(position)
                remainder = handle.read(size) + remainder
                lines = remainder.split(b"\n")
                remainder = lines[0]
                for raw in reversed(lines[1:]):
                    if not raw:
                        continue
                    value = decode(raw)
                    if value is None:
                        continue
                    timestamp = _parse_event_time(value.get("timestamp") or value.get("logged_at"))
                    if since_time is not None and timestamp is not None and timestamp < since_time:
                        stop_at_since = True
                        break
                    if _event_matches(
                        value,
                        event_filter=event_filter,
                        component_filter=component_filter,
                        trace_id=trace_id,
                        since=since_time,
                    ):
                        matches.append(value)
                        if len(matches) >= limit:
                            break
            if position == 0 and remainder and len(matches) < limit and not stop_at_since:
                value = decode(remainder)
                if value is not None and _event_matches(
                    value,
                    event_filter=event_filter,
                    component_filter=component_filter,
                    trace_id=trace_id,
                    since=since_time,
                ):
                    matches.append(value)
    except OSError:
        return []
    return list(reversed(matches))


def _event_paths(stream: str, *, since: datetime | str | None = None) -> list[Path]:
    paths: list[Path] = []
    since_time = _parse_event_time(since)
    legacy = EVENTS_DIR / f"{stream}.jsonl"
    if legacy.exists():
        paths.append(legacy)
    shards = []
    for path in EVENTS_DIR.glob(f"{stream}-*.jsonl"):
        match = EVENT_SHARD_RE.match(path.name)
        if not match or match.group("stream") != stream:
            continue
        try:
            shard_date = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
        except ValueError:
            continue
        if since_time is None or shard_date >= since_time.astimezone(timezone.utc).date():
            shards.append(path)
    paths.extend(sorted(shards))
    return paths


def read_events(
    stream: str = "backend",
    limit: int = DEFAULT_EVENT_TAIL_LIMIT,
    *,
    event_filter: str | Collection[str] | None = None,
    component_filter: str | Collection[str] | None = None,
    trace_id: str | None = None,
    since: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Read bounded recent events across legacy and daily-sharded files."""

    limit = max(0, min(int(limit), 10000))
    collected: list[dict[str, Any]] = []
    for path in reversed(_event_paths(stream, since=since)):
        remaining = limit - len(collected)
        if remaining <= 0:
            break
        filtered_scan_limit = 16 * 1024 * 1024 if trace_id else None
        chunk = tail_jsonl(
            path,
            remaining,
            event_filter=event_filter,
            component_filter=component_filter,
            trace_id=trace_id,
            since=since,
            max_scan_bytes=filtered_scan_limit,
        )
        collected = chunk + collected
    return collected[-limit:] if limit else []


def read_all_events(
    limit_per_stream: int = DEFAULT_EVENT_TAIL_LIMIT,
    *,
    event_filter: str | Collection[str] | None = None,
    component_filter: str | Collection[str] | None = None,
    trace_id: str | None = None,
    since: datetime | str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for stream in EVENT_STREAMS:
        records.extend(
            read_events(
                stream,
                limit_per_stream,
                event_filter=event_filter,
                component_filter=component_filter,
                trace_id=trace_id,
                since=since,
            )
        )
    return sorted(records, key=lambda record: str(record.get("timestamp") or record.get("logged_at") or ""))


def prune_event_shards(
    *,
    retention_days: dict[str, int] | None = None,
    now: datetime | None = None,
) -> int:
    """Delete only dated shards older than retention; never parse active files."""

    retention_days = retention_days or {"backend": 14, "mirror": 30, "notifications": 30}
    current = (now or utc_now()).astimezone(timezone.utc).date()
    deleted = 0
    for path in EVENTS_DIR.glob("*.jsonl"):
        match = EVENT_SHARD_RE.match(path.name)
        if not match or match.group("stream") not in retention_days:
            continue
        try:
            shard_date = datetime.strptime(match.group("date"), "%Y-%m-%d").date()
            if (current - shard_date).days > max(1, int(retention_days[match.group("stream")])):
                path.unlink()
                deleted += 1
        except (OSError, ValueError):
            continue
    return deleted


def initialise_backend_process(database_path: Path, app_version: str = "0.1.0") -> None:
    """Configure logging and emit one process STARTED event per interpreter."""

    global _PROCESS_STARTED
    configure_runtime_logging()
    if _PROCESS_STARTED:
        return
    previous_start: dict[str, Any] | None = None
    previous_shutdown = False
    archive_legacy_event_file(BACKEND_EVENTS_PATH)
    for record in read_events("backend", limit=5000):
        if record.get("event") == "BACKEND_PROCESS_STARTED":
            previous_start = record
            previous_shutdown = False
        elif record.get("event") == "BACKEND_SHUTDOWN_COMPLETED" and previous_start:
            if record.get("instance_id") == previous_start.get("instance_id"):
                previous_shutdown = True
    if previous_start and not previous_shutdown and previous_start.get("instance_id") != BACKEND_INSTANCE_ID:
        append_event(
            "backend",
            "PREVIOUS_BACKEND_INSTANCE_UNCLEAN_EXIT",
            level="WARNING",
            component="backend",
            metadata={
                "previous_instance_id": previous_start.get("instance_id"),
                "previous_started_at": previous_start.get("timestamp"),
                "reason": "STARTED without a matching SHUTDOWN_COMPLETED",
            },
            previous_instance_id=previous_start.get("instance_id"),
        )
    append_event(
        "backend",
        "BACKEND_PROCESS_STARTED",
        component="backend",
        metadata={
            "pid": os.getpid(),
            "python_version": platform.python_version(),
            "app_version": app_version,
            "git_commit": _git_commit(),
            "working_directory": str(PROJECT_ROOT),
            "database_path": str(database_path),
            "start_time": utc_iso(PROCESS_STARTED_AT),
        },
        pid=os.getpid(),
        python_version=platform.python_version(),
        app_version=app_version,
        git_commit=_git_commit(),
        working_directory=str(PROJECT_ROOT),
        database_path=str(database_path),
    )
    logging.getLogger("radar").info(
        "BACKEND_PROCESS_STARTED instance_id=%s pid=%s database_path=%s",
        BACKEND_INSTANCE_ID,
        os.getpid(),
        database_path,
    )
    _PROCESS_STARTED = True


def backend_ready(*, tasks: list[str], db_ready: bool, scheduler_started: bool, mirror_started: bool, alert_manager_ready: bool) -> None:
    append_event(
        "backend",
        "BACKEND_READY",
        component="backend",
        result="ready",
        metadata={
            "db_ready": db_ready,
            "scheduler_started": scheduler_started,
            "heartbeat_task_started": "backend-heartbeat" in tasks,
            "mirror_task_started": mirror_started,
            "alert_manager_ready": alert_manager_ready,
            "tasks": tasks,
        },
        tasks=tasks,
        db_ready=db_ready,
        scheduler_started=scheduler_started,
        mirror_started=mirror_started,
        alert_manager_ready=alert_manager_ready,
    )


def backend_shutdown_started(reason: str = "lifespan_shutdown") -> None:
    append_event(
        "backend",
        "BACKEND_SHUTDOWN_STARTED",
        component="backend",
        metadata={"reason": reason, "uptime_seconds": round((utc_now() - PROCESS_STARTED_AT).total_seconds(), 3)},
        reason=reason,
        uptime_seconds=round((utc_now() - PROCESS_STARTED_AT).total_seconds(), 3),
    )


def backend_shutdown_completed(reason: str = "lifespan_shutdown") -> None:
    global _PROCESS_SHUTDOWN_RECORDED
    if _PROCESS_SHUTDOWN_RECORDED:
        return
    append_event(
        "backend",
        "BACKEND_SHUTDOWN_COMPLETED",
        component="backend",
        result="stopped",
        metadata={"reason": reason, "uptime_seconds": round((utc_now() - PROCESS_STARTED_AT).total_seconds(), 3)},
        reason=reason,
        uptime_seconds=round((utc_now() - PROCESS_STARTED_AT).total_seconds(), 3),
    )
    _PROCESS_SHUTDOWN_RECORDED = True


def install_exception_hooks() -> None:
    def excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
        append_event(
            "backend",
            "UNHANDLED_EXCEPTION",
            level="CRITICAL",
            component="backend",
            error_type=exc_type.__name__,
            metadata={"exception_type": exc_type.__name__, "message": redact_secret(exc_value), "traceback": redact_secret("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))},
            exception_type=exc_type.__name__,
            message=redact_secret(exc_value),
        )
        _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook
    if _ORIGINAL_THREADING_EXCEPTHOOK:
        def threading_hook(args: Any) -> None:
            append_event(
                "backend",
                "UNHANDLED_EXCEPTION",
                level="CRITICAL",
                component="backend",
                error_type=getattr(args.exc_type, "__name__", "unknown"),
                metadata={"thread": getattr(args.thread, "name", None), "message": redact_secret(args.exc_value)},
                task=getattr(args.thread, "name", None),
                message=redact_secret(args.exc_value),
            )
            _ORIGINAL_THREADING_EXCEPTHOOK(args)
        threading.excepthook = threading_hook


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    def handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exception = context.get("exception")
        message = context.get("message") or (str(exception) if exception else "asyncio exception")
        append_event(
            "backend",
            "UNHANDLED_EXCEPTION",
            level="ERROR",
            component="backend",
            error_type=type(exception).__name__ if exception else "asyncio_error",
            metadata={"task": str(context.get("task") or context.get("future") or "unknown"), "message": redact_secret(message)},
            task=str(context.get("task") or context.get("future") or "unknown"),
            message=redact_secret(message),
        )
        logging.getLogger("radar").error("UNHANDLED_EXCEPTION task=%s message=%s", context.get("task") or context.get("future"), redact_secret(message))
        current_loop.default_exception_handler(context)
    loop.set_exception_handler(handler)


class TaskSupervisor:
    """Small registry that makes long-lived asyncio task death observable."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def create_task(self, coroutine: Any, task_name: str) -> asyncio.Task[Any]:
        started_at = utc_now()
        record = {
            "task_name": task_name,
            "status": "running",
            "started_at": utc_iso(started_at),
            "restart_count": 0,
            "task_id": None,
        }
        self.records[task_name] = record
        append_event("backend", "TASK_STARTED", component="backend", metadata=record.copy(), task_name=task_name)
        task = asyncio.create_task(self._run(coroutine, task_name, started_at), name=task_name)
        record["task_id"] = id(task)
        self._tasks[task_name] = task
        task.add_done_callback(self._consume_exception)
        return task

    async def _run(self, coroutine: Any, task_name: str, started_at: datetime) -> Any:
        try:
            return await coroutine
        except asyncio.CancelledError:
            self._finish(task_name, "stopped", started_at, result="cancelled")
            raise
        except BaseException as exc:
            self._finish(
                task_name,
                "failed",
                started_at,
                level="ERROR",
                result="failed",
                error_type=type(exc).__name__,
                error=redact_secret(exc),
                traceback=redact_secret("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
            )
            logging.getLogger("radar").exception("TASK_FAILED task_name=%s", task_name)
            raise
        else:
            self._finish(task_name, "stopped", started_at, result="completed")

    def _finish(self, task_name: str, status: str, started_at: datetime, *, level: str = "INFO", **fields: Any) -> None:
        ended_at = utc_now()
        record = self.records.setdefault(task_name, {"task_name": task_name})
        record.update({"status": status, "finished_at": utc_iso(ended_at), "uptime_seconds": round((ended_at - started_at).total_seconds(), 3)})
        append_event("backend", f"TASK_{status.upper()}", level=level, component="backend", metadata=record.copy(), task_name=task_name, **fields)

    @staticmethod
    def _consume_exception(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        try:
            task.exception()
        except BaseException:
            return

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.records.values()]

    def running_names(self) -> list[str]:
        return [name for name, task in self._tasks.items() if not task.done()]


async def event_loop_watchdog(stop_event: asyncio.Event, supervisor: TaskSupervisor, interval_seconds: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval_seconds
    while not stop_event.is_set():
        await asyncio.sleep(interval_seconds)
        actual = loop.time()
        lag_ms = max(0.0, (actual - expected) * 1000)
        expected = actual + interval_seconds
        if lag_ms >= 2000:
            level = "ERROR" if lag_ms >= 10000 else "WARNING"
            append_event(
                "backend",
                "EVENT_LOOP_LAG_DETECTED",
                level=level,
                component="backend",
                duration_ms=round(lag_ms),
                metadata={"lag_ms": round(lag_ms, 3), "running_tasks": supervisor.running_names()},
                lag_ms=round(lag_ms, 3),
                running_tasks=supervisor.running_names(),
            )
            logging.getLogger("radar").warning("EVENT_LOOP_LAG_DETECTED lag_ms=%s running_tasks=%s", round(lag_ms), supervisor.running_names())


def prune_jsonl(path: Path, *, max_age_days: int = 30, now: datetime | None = None) -> int:
    """Best-effort streaming age pruning for a legacy or small JSONL file."""

    if not path.exists():
        return 0
    cutoff = (now or utc_now()) - timedelta(days=max_age_days)
    try:
        with _WRITE_LOCK:
            temp = path.with_suffix(path.suffix + ".tmp")
            deleted = 0
            with path.open("r", encoding="utf-8") as source, temp.open("w", encoding="utf-8") as destination:
                for line in source:
                    try:
                        record = json.loads(line)
                        stamp = record.get("timestamp") or record.get("logged_at")
                        parsed = _parse_event_time(stamp)
                    except (TypeError, json.JSONDecodeError):
                        parsed = None
                    if parsed and parsed < cutoff:
                        deleted += 1
                    else:
                        destination.write(line)
            if deleted:
                temp.replace(path)
            else:
                temp.unlink(missing_ok=True)
            return deleted
    except OSError:
        try:
            path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)
        except OSError:
            pass
        return 0


def register_atexit_shutdown() -> None:
    def _shutdown() -> None:
        if _PROCESS_STARTED and not _PROCESS_SHUTDOWN_RECORDED:
            backend_shutdown_started("process_exit")
            backend_shutdown_completed("process_exit")
    atexit.register(_shutdown)
