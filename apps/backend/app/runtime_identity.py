from __future__ import annotations

import hashlib
import marshal
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from .review_common import sha256_json, utc_text


def _code_hash(callable_value: Any) -> str | None:
    function = getattr(callable_value, "__func__", callable_value)
    code = getattr(function, "__code__", None)
    if code is None:
        return None
    return hashlib.sha256(marshal.dumps(code)).hexdigest()


def _windows_process_creation_token(handle) -> str | None:
    import ctypes
    from ctypes import wintypes

    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    kernel.GetProcessTimes.restype = wintypes.BOOL
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                  ctypes.byref(wintypes.FILETIME()), ctypes.byref(wintypes.FILETIME())):
        return None
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return str(ticks)


def _current_process_start() -> tuple[str | None, str | None]:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = ()
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel.GetCurrentProcess()
        token = _windows_process_creation_token(handle)
        if token is None:
            return None, None
        unix_seconds = int(token) / 10_000_000 - 11_644_473_600
        return token, utc_text(datetime.fromtimestamp(unix_seconds, UTC))
    try:
        raw = open(f"/proc/{os.getpid()}/stat", encoding="utf-8").read()
        tail = raw[raw.rfind(")") + 2 :].split()
        token = tail[19]
        return token, None
    except (OSError, IndexError, ValueError):
        return None, None


def capture_owner(runtime_id: str | None = None) -> dict[str, Any]:
    token, started_at = _current_process_start()
    return {
        "runtime_id": runtime_id,
        "pid": os.getpid(),
        "process_start_token": token,
        "process_started_at": started_at,
        "platform": sys.platform,
    }


def owner_status(owner: dict[str, Any], *, current_runtime_id: str | None = None) -> bool | None:
    """Return True/False only when liveness is proven; None means unknown."""
    if current_runtime_id and owner.get("runtime_id") == current_runtime_id:
        return True
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError):
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0
        WAIT_TIMEOUT = 258
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            return False if error == 87 else None
        try:
            state = kernel.WaitForSingleObject(handle, 0)
            if state == WAIT_OBJECT_0:
                return False
            if state != WAIT_TIMEOUT:
                return None
            expected = owner.get("process_start_token")
            actual = _windows_process_creation_token(handle)
            if expected and actual and str(expected) != actual:
                return False
            return True
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None
    expected = owner.get("process_start_token")
    if expected:
        try:
            raw = open(f"/proc/{pid}/stat", encoding="utf-8").read()
            actual = raw[raw.rfind(")") + 2 :].split()[19]
            if str(expected) != actual:
                return False
        except (OSError, IndexError):
            return None
    return True


def capture_runtime_identity(settings: Any, client: Any) -> dict[str, Any]:
    from . import collector_health, db, deepseek, intelligence, main, pipeline, reply_context
    from .version import APP_VERSION, runtime_commit

    runtime_id = str(uuid.uuid4())
    configured_model = str(getattr(client, "model", None) or getattr(settings, "deepseek_model", "unknown"))
    provider = "deepseek" if isinstance(client, deepseek.DeepSeekClient) else type(client).__name__
    config = {
        "provider": provider,
        "model": configured_model,
        "timeout_seconds": getattr(settings, "deepseek_timeout_seconds", None),
        "retries": getattr(settings, "deepseek_retries", None),
        "judge_interval_seconds": getattr(settings, "judge_interval_seconds", None),
    }
    prompt_material = intelligence.judge_prompt_identity_material()
    prompt = {
        "version": intelligence.JUDGE_PROMPT_VERSION,
        "sha256": sha256_json(prompt_material),
    }
    callables = {
        "main.create_app": main.create_app,
        "db.Database.judgement_context": db.Database.judgement_context,
        "db.Database._insert_judgement": db.Database._insert_judgement,
        "pipeline.IntelligencePipeline._run_judge": pipeline.IntelligencePipeline._run_judge,
        "intelligence.judge": intelligence.judge,
        "reply_context.ReplyContexts.input": reply_context.ReplyContexts.input,
        "collector_health.collector_health": collector_health.collector_health,
        "active_client.complete_json": getattr(type(client), "complete_json", None),
    }
    code_hashes = {name: _code_hash(function) for name, function in callables.items()}
    algorithm = {"version": "prediction-ledger-core-v1", "callable_code_hashes": code_hashes}
    return {
        "runtime_id": runtime_id,
        "app_version": APP_VERSION,
        "program_commit": None,
        "disk_head": runtime_commit(),
        "algorithm": algorithm,
        "algorithm_hash": sha256_json(algorithm),
        "config": config,
        "config_hash": sha256_json(config),
        "model": configured_model,
        "prompt": prompt,
        "runtime_fingerprint": sha256_json({
            "app_version": APP_VERSION,
            "algorithm_hash": sha256_json(algorithm),
            "config_hash": sha256_json(config),
            "prompt": prompt,
        }),
        "identity_scope": sorted(callables),
        "owner": capture_owner(runtime_id),
        "captured_at": utc_text(),
    }
