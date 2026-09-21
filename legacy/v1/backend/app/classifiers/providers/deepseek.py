from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas import ClassificationOutput, RuleClassification, TranslationOutput

from .base import ProviderResult, TranslationResult


SYSTEM_PROMPT = """You classify one public Tweet by Tibo (@thsottiaux) for Codex Reset Radar.
Your task is semantic classification, not prediction of OpenAI internal plans.
Use only the current Tweet and the supplied context. Distinguish jokes, metaphors,
denials, announcements, in-progress actions, and completed resets. Do not raise
confidence because a user wants a reset. Do not invent categories. Return JSON only
with exactly these fields: category, confidence, urgency, explicitness, reason.

Category boundary definitions:
- reset_hint: an indirect, implied, playful, or metaphorical suggestion that a reset
  may happen, without an explicit reset event or schedule.
- reset_announcement: an explicit statement that a reset will happen in the future,
  including a future time such as tomorrow, by 8pm, or around 2pm.
- reset_in_progress: an explicit statement that reset propagation/distribution is
  currently underway, such as is rolling out, propagating, or being distributed.
- reset_confirmed: an explicit statement that the reset has completed or landed,
  including has landed, has been propagated to accounts, or is available now.
- quota_information: usage-limit, quota, policy, or cycle information without an
  actual reset event. A banked reset is still a reset event, not ordinary quota:
  “banked reset will be distributed” is reset_announcement and “banked reset has
  landed” is reset_confirmed, unless the context clearly says rollout is underway.
- reset_denial: an explicit denial such as no reset or not resetting. Do not treat
  “not today, maybe tomorrow” as a denial when the full text discusses a future reset.

Treat reset, resets, resetting, reseted, and resetted as the same reset vocabulary.
Handle today, tomorrow, soon, later, by, around, and not today as time semantics.
Do not infer a reset from a generic Codex milestone or a generic usage mention.
Return only the allowed category values and keep reason to 1-3 short sentences.

Allowed category: unrelated, codex_related, quota_information, reset_hint,
reset_announcement, reset_in_progress, reset_confirmed, reset_denial.
Allowed urgency: now, within_6h, within_24h, within_3d, unknown.
Allowed explicitness: explicit, implicit, unclear.
"""

TRANSLATION_SYSTEM_PROMPT = """Translate one public Tweet by Tibo (@thsottiaux) into natural Simplified Chinese.
Return JSON only with exactly one field: translation_zh.
Preserve the original meaning, tone, uncertainty, jokes, metaphors, names, product names,
numbers, URLs, and line breaks when useful. Understand the Codex Reset Radar context,
including Codex, quota, limits, reset, reset button, banked reset, milestone, usage,
Plus, and ChatGPT Work. Do not add facts that are not present in the original.
For metaphors such as 'dust off the button', keep the metaphor understandable in Chinese
instead of translating it into a literal but misleading sentence.
"""


class DeepSeekProviderError(RuntimeError):
    pass


class DeepSeekProvider:
    def __init__(self, api_key: str, model_name: str, base_url: str, timeout_seconds: float = 30.0):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def classify(self, context: dict[str, Any], rule_result: RuleClassification) -> ProviderResult:
        user_payload = {
            "current_tweet": context.get("current_tweet", {}),
            "is_reply": context.get("current_tweet", {}).get("is_reply", False),
            "parent_context": context.get("parent_context"),
            "recent_related_tweets": context.get("recent_related_tweets", []),
            "last_confirmed_reset": context.get("last_confirmed_reset"),
            "recent_status_events": context.get("recent_status_events", []),
            "rule_result": rule_result.model_dump(),
        }
        body = {
            "model": self.model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise DeepSeekProviderError("DeepSeek timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise DeepSeekProviderError(f"DeepSeek HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekProviderError("DeepSeek connection error") from exc
        except ValueError as exc:
            raise DeepSeekProviderError("DeepSeek returned invalid JSON") from exc

        try:
            message = payload["choices"][0]["message"]["content"]
            if isinstance(message, dict):
                parsed = message
            else:
                content = str(message).strip()
                if content.startswith("```"):
                    content = content.removeprefix("```").removeprefix("json").removesuffix("```").strip()
                parsed = json.loads(content)
            result = ClassificationOutput.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise DeepSeekProviderError("DeepSeek response schema validation failed") from exc

        usage = payload.get("usage") or {}
        return ProviderResult(
            result=result,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def translate(self, text: str, *, context: dict[str, Any] | None = None) -> TranslationResult:
        user_payload = {
            "original_text": text,
            "context": context or {},
        }
        body = {
            "model": self.model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise DeepSeekProviderError("DeepSeek translation timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise DeepSeekProviderError(f"DeepSeek translation HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekProviderError("DeepSeek translation connection error") from exc
        except ValueError as exc:
            raise DeepSeekProviderError("DeepSeek translation returned invalid JSON") from exc

        try:
            message = payload["choices"][0]["message"]["content"]
            if isinstance(message, dict):
                parsed = message
            else:
                content = str(message).strip()
                if content.startswith("```"):
                    content = content.removeprefix("```").removeprefix("json").removesuffix("```").strip()
                parsed = json.loads(content)
            result = TranslationOutput.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise DeepSeekProviderError("DeepSeek translation response schema validation failed") from exc

        usage = payload.get("usage") or {}
        return TranslationResult(
            translation_zh=result.translation_zh,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
