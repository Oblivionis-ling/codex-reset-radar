"""Single-flight, bounded private worker; Backend has no ML dependencies."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import hashlib
import os
from pathlib import Path
import uuid

from .config import REPOSITORY_ROOT


@dataclass(frozen=True)
class DecisionSettings:
    mode: str = "deepseek_only"
    model_path: str = ""
    revision: str = ""
    device: str = "cpu"
    timeout: float = 15.0
    startup_timeout: float = 90.0
    threads: int = 2
    fallback: str = "deepseek_only"
    python: str = str(REPOSITORY_ROOT / "apps/laya-worker/.venv/Scripts/python.exe")

    def __post_init__(self):
        if self.mode not in {"deepseek_only", "deepseek_laya"}:
            raise ValueError("INVALID_DECISION_MODE")
        if self.fallback not in {"deepseek_only", "unknown"}:
            raise ValueError("INVALID_LAYA_FALLBACK")
        if self.timeout <= 0 or self.startup_timeout <= 0 or not 1 <= self.threads <= 4:
            raise ValueError("INVALID_LAYA_RESOURCE_LIMIT")

    def identity(self):
        from .hybrid_decision import EVIDENCE_VERSION, QUESTION_VERSION, VALIDATION_VERSION
        return hashlib.sha256(json.dumps(dict(mode=self.mode, revision=self.revision, device=self.device,
            fallback=self.fallback, evidence=EVIDENCE_VERSION, questions=QUESTION_VERSION,
            validation=VALIDATION_VERSION), sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_environment(cls):
        return cls(mode=os.getenv("CRR_DECISION_MODE", "deepseek_only"),
                   model_path=os.getenv("CRR_LAYA_MODEL_PATH", ""),
                   revision=os.getenv("CRR_LAYA_CHECKPOINT_REVISION", ""),
                   device=os.getenv("CRR_LAYA_DEVICE", "cpu"),
                   timeout=float(os.getenv("CRR_LAYA_TIMEOUT_SECONDS", "15")),
                   startup_timeout=float(os.getenv("CRR_LAYA_STARTUP_SECONDS", "90")),
                   threads=int(os.getenv("CRR_LAYA_THREADS", "2")),
                   fallback=os.getenv("CRR_LAYA_FALLBACK", "deepseek_only"),
                   python=os.getenv("CRR_LAYA_PYTHON", cls.python))


class LayaFailure(RuntimeError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


class LayaWorker:
    def __init__(self, settings: DecisionSettings):
        self.settings = settings
        self.process = None
        self.identity = None
        self._lock = asyncio.Lock()

    async def close(self):
        process, self.process = self.process, None
        self.identity = None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def _read(self):
        line = await self.process.stdout.readline()
        if not line:
            raise LayaFailure("WORKER_EXITED")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise LayaFailure("WORKER_PROTOCOL_ERROR")
        return value

    async def _start(self):
        cfg = self.settings
        if not cfg.model_path or not Path(cfg.model_path).is_dir() or not Path(cfg.python).is_file():
            raise LayaFailure("MODEL_OR_ENV_MISSING")
        if not cfg.revision:
            raise LayaFailure("REVISION_MISSING")
        env = dict(os.environ, PYTHONUTF8="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        # Worker has no need for Backend provider/notification credentials.
        for name in list(env):
            if any(word in name.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "SENDKEY")):
                env.pop(name)
        self.process = await asyncio.create_subprocess_exec(
            cfg.python, "-u", str(REPOSITORY_ROOT / "apps/laya-worker/worker.py"),
            str(Path(cfg.model_path).resolve()), cfg.device, str(cfg.threads),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, limit=262144)
        ready = await asyncio.wait_for(self._read(), timeout=cfg.startup_timeout)
        if ready.get("status") != "READY" or ready.get("identity", {}).get("revision") != cfg.revision:
            raise LayaFailure("WORKER_IDENTITY_MISMATCH")
        self.identity = ready["identity"]

    async def predict(self, state, questions):
        if self._lock.locked():
            raise LayaFailure("WORKER_BUSY")
        async with self._lock:
            try:
                if self.process is None or self.process.returncode is not None:
                    await self.close()
                    await self._start()
                request_id = uuid.uuid4().hex
                data = json.dumps(dict(id=request_id, state=state, questions=questions), ensure_ascii=False).encode() + b"\n"
                if len(data) > 131072:
                    raise LayaFailure("INPUT_TOO_LONG")
                async def exchange():
                    self.process.stdin.write(data)
                    await self.process.stdin.drain()
                    return await self._read()
                value = await asyncio.wait_for(exchange(), timeout=self.settings.timeout)
                if value.get("id") != request_id:
                    raise LayaFailure("WORKER_RESPONSE_MISMATCH")
                if value.get("error"):
                    raise LayaFailure(value["error"], value)
                return value
            except asyncio.CancelledError:
                await self.close()
                raise
            except Exception as error:
                await self.close()
                if isinstance(error, LayaFailure):
                    raise
                raise LayaFailure("WORKER_TIMEOUT" if isinstance(error, TimeoutError)
                                  else "WORKER_FAILURE") from error
