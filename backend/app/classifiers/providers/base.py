from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas import ClassificationOutput, RuleClassification


@dataclass(frozen=True)
class ProviderResult:
    result: ClassificationOutput
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class TranslationResult:
    translation_zh: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class AIProvider(Protocol):
    model_name: str

    async def classify(self, context: dict[str, Any], rule_result: RuleClassification) -> ProviderResult:
        ...
