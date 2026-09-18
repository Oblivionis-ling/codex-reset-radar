from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from .logging_runtime import RuntimeLog


class DeepSeekError(RuntimeError):
    def __init__(self, message: str, *, category: str = "unknown", retryable: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        retries: int,
        runtime_log: RuntimeLog,
        max_requests: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.runtime_log = runtime_log
        self.max_requests = max_requests
        self.requests_started = 0
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def close(self) -> None:
        await self._client.aclose()

    async def complete_json(self, *, operation: str, system: str, user: str) -> dict[str, Any]:
        if not self.api_key:
            raise DeepSeekError("DeepSeek API key is not configured", category="configuration", retryable=False)
        last_error: DeepSeekError | None = None
        for attempt in range(1, self.retries + 2):
            if self.max_requests is not None and self.requests_started >= self.max_requests:
                raise DeepSeekError("model request budget exhausted", category="budget", retryable=False)
            self.requests_started += 1
            started = time.perf_counter()
            self.runtime_log.write("llm", "LLM_REQUEST_STARTED", metadata={"operation": operation, "model": self.model, "attempt": attempt})
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip().startswith("```"):
                    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                result = json.loads(content) if isinstance(content, str) else content
                if not isinstance(result, dict):
                    raise ValueError("model response is not a JSON object")
                self.runtime_log.write("llm", "LLM_REQUEST_SUCCEEDED", metadata={
                    "operation": operation, "model": self.model, "attempt": attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                })
                return result
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                retryable = status in {408, 409, 429} or status >= 500
                category = "auth" if status in {401, 403} else "rate_limit" if status == 429 else "http"
                last_error = DeepSeekError(f"DeepSeek HTTP {status}", category=category, retryable=retryable)
            except (httpx.ConnectError, httpx.NetworkError) as error:
                last_error = DeepSeekError(f"DeepSeek network error: {type(error).__name__}", category="network", retryable=True)
            except httpx.TimeoutException:
                last_error = DeepSeekError("DeepSeek request timed out", category="timeout", retryable=True)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = DeepSeekError(f"Invalid DeepSeek response: {type(error).__name__}", category="invalid_response", retryable=attempt <= self.retries)
            self.runtime_log.write("llm", "LLM_REQUEST_FAILED", result="failure", metadata={
                "operation": operation, "model": self.model, "attempt": attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "error_category": last_error.category, "retryable": last_error.retryable,
            })
            if not last_error.retryable or attempt > self.retries:
                raise last_error
            await asyncio.sleep(min(2 ** (attempt - 1), 4))
        raise last_error or DeepSeekError("DeepSeek request failed")
