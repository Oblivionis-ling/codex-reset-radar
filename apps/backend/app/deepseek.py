from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from .logging_runtime import RuntimeLog
from .prediction_ledger import current_attempt_tracker
from .review_common import utc_text


def build_request_payload(model: str, system: str, user: str) -> dict[str, Any]:
    """Build the exact non-secret JSON body sent by the existing client."""
    return {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }


class DeepSeekError(RuntimeError):
    def __init__(self, message: str, *, category: str = "unknown", retryable: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


class DeepSeekClient:
    ledger_attempts_enabled = True

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
        tracker = current_attempt_tracker()
        if operation == "radar_judge" and tracker is None:
            raise DeepSeekError("Judge request has no durable attempt context", category="ledger", retryable=False)
        request_payload = build_request_payload(self.model, system, user)
        last_error: DeepSeekError | None = None
        retry_of: str | None = None
        for attempt in range(1, self.retries + 2):
            if self.max_requests is not None and self.requests_started >= self.max_requests:
                raise DeepSeekError("model request budget exhausted", category="budget", retryable=False)
            if tracker:
                tracker.prepare_request(request_payload)
            attempt_ref = tracker.begin_attempt(retry_of=retry_of) if tracker else None
            self.requests_started += 1
            started = time.monotonic()
            received_at: str | None = None
            http_status: int | None = None
            self.runtime_log.write("llm", "LLM_REQUEST_STARTED", metadata={"operation": operation, "model": self.model, "attempt": attempt})
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=request_payload,
                )
                received_at = utc_text()
                http_status = response.status_code
                if tracker and attempt_ref:
                    tracker.append_event(attempt_ref.attempt_id, "response_received",
                        received_at=received_at, http={"status_code": http_status})
                response.raise_for_status()
                payload = response.json()
                reported_model = payload.get("model") if isinstance(payload, dict) else None
                if isinstance(reported_model, str) and reported_model.strip():
                    reported_model_missing_reason = None
                elif not isinstance(payload, dict) or "model" not in payload:
                    reported_model = None
                    reported_model_missing_reason = "model_field_missing"
                else:
                    reported_model = None
                    reported_model_missing_reason = "model_field_invalid"
                if tracker and attempt_ref:
                    tracker.append_event(
                        attempt_ref.attempt_id, "response_model_reported",
                        received_at=received_at,
                        reported_model=reported_model,
                        reported_model_source="deepseek_api_response.model",
                        reported_model_missing_reason=reported_model_missing_reason,
                    )
                usage = self._usage(payload)
                if tracker and attempt_ref and usage is not None:
                    tracker.append_event(attempt_ref.attempt_id, "usage_reported",
                        usage=usage, usage_source="deepseek_api_response.usage")
                content = payload["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip().startswith("```"):
                    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                result = json.loads(content) if isinstance(content, str) else content
                if not isinstance(result, dict):
                    raise ValueError("model response is not a JSON object")
                if tracker and attempt_ref:
                    tracker.append_event(attempt_ref.attempt_id, "response_json_decoded",
                        received_at=received_at,
                        http={"status_code": http_status},
                        duration_ms=round((time.monotonic() - started) * 1000),
                        usage=usage,
                        usage_source="deepseek_api_response.usage" if usage is not None else None)
                self.runtime_log.write("llm", "LLM_REQUEST_SUCCEEDED", metadata={
                    "operation": operation, "model": self.model, "attempt": attempt,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                })
                return result
            except asyncio.CancelledError:
                if tracker and attempt_ref:
                    tracker.append_event(attempt_ref.attempt_id, "cancelled",
                        failure_terminal=True, attempt_finished_at=utc_text(),
                        duration_ms=round((time.monotonic() - started) * 1000),
                        received_at=received_at,
                        http={"status_code": http_status} if http_status is not None else None)
                raise
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                retryable = status in {408, 409, 429} or status >= 500
                category = "auth" if status in {401, 403} else "rate_limit" if status == 429 else "http"
                last_error = DeepSeekError(f"DeepSeek HTTP {status}", category=category, retryable=retryable)
                event_type = "http_failure"
            except (httpx.ConnectError, httpx.NetworkError) as error:
                last_error = DeepSeekError(f"DeepSeek network error: {type(error).__name__}", category="network", retryable=True)
                event_type = "network_failure"
            except httpx.TimeoutException:
                last_error = DeepSeekError("DeepSeek request timed out", category="timeout", retryable=True)
                event_type = "timeout"
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = DeepSeekError(f"Invalid DeepSeek response: {type(error).__name__}", category="invalid_response", retryable=attempt <= self.retries)
                event_type = "parse_failure"
            if tracker and attempt_ref:
                tracker.append_event(attempt_ref.attempt_id, event_type,
                    failure_terminal=True, attempt_finished_at=utc_text(),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    received_at=received_at,
                    http={"status_code": http_status, "category": last_error.category,
                          "retryable": last_error.retryable} if http_status is not None else None)
            self.runtime_log.write("llm", "LLM_REQUEST_FAILED", result="failure", metadata={
                "operation": operation, "model": self.model, "attempt": attempt,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "error_category": last_error.category, "retryable": last_error.retryable,
            })
            if not last_error.retryable or attempt > self.retries:
                raise last_error
            await asyncio.sleep(min(2 ** (attempt - 1), 4))
            retry_of = attempt_ref.attempt_id if attempt_ref else None
        raise last_error or DeepSeekError("DeepSeek request failed")

    @staticmethod
    def _usage(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
            return None
        allowed = {
            "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
            "reasoning_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
            "prompt_tokens_details", "completion_tokens_details",
        }

        def token_fields(value: Any) -> Any:
            if not isinstance(value, dict):
                return None
            result: dict[str, Any] = {}
            for key, child in value.items():
                name = str(key)
                if name not in allowed:
                    continue
                if isinstance(child, dict):
                    nested = token_fields(child)
                    if nested:
                        result[name] = nested
                elif isinstance(child, (int, float)) and not isinstance(child, bool):
                    result[name] = child
            return result

        usage = token_fields(payload["usage"])
        return usage or None
