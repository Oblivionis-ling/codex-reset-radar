from __future__ import annotations

from dataclasses import dataclass

from app.schemas import ClassificationOutput, RuleClassification


@dataclass(frozen=True)
class ClassificationDecision:
    result: ClassificationOutput
    conflict: bool = False
    reason: str = ""


RESET_EVENT_CATEGORIES = {
    "reset_announcement",
    "reset_in_progress",
    "reset_confirmed",
}


def resolve_classification(rule: RuleClassification, ai: ClassificationOutput | None) -> ClassificationDecision:
    if ai is None:
        if not rule.requires_ai:
            return ClassificationDecision(
                result=ClassificationOutput(
                    category=rule.category,
                    confidence=rule.confidence,
                    urgency=rule.urgency,
                    explicitness=rule.explicitness,
                    reason=rule.reason,
                ),
                reason="rule_only",
            )
        return ClassificationDecision(
            result=ClassificationOutput(
                category=rule.category,
                confidence=rule.confidence,
                urgency=rule.urgency,
                explicitness=rule.explicitness,
                reason=f"{rule.reason} AI unavailable; using rule fallback.",
            ),
            reason="ai_unavailable_fallback",
        )

    if rule.category == "reset_denial" and rule.confidence >= 0.95:
        conflict = ai.category != rule.category
        reason = "Explicit denial takes precedence over conflicting AI output." if conflict else ai.reason
        return ClassificationDecision(
            result=ClassificationOutput(
                category=rule.category,
                confidence=rule.confidence if not conflict else min(rule.confidence, ai.confidence) * 0.9,
                urgency=rule.urgency,
                explicitness=rule.explicitness,
                reason=reason,
            ),
            conflict=conflict,
            reason="rule_denial_precedence",
        )

    if rule.category in {"reset_confirmed", "reset_in_progress", "reset_announcement"} and rule.confidence >= 0.95:
        conflict = ai.category != rule.category
        return ClassificationDecision(
            result=ClassificationOutput(
                category=rule.category,
                confidence=rule.confidence if conflict else max(rule.confidence, ai.confidence),
                urgency=ai.urgency if not conflict else rule.urgency,
                explicitness=ai.explicitness if not conflict else rule.explicitness,
                reason="Explicit rule result retained." if conflict else ai.reason,
            ),
            conflict=conflict,
            reason="explicit_rule_precedence" if conflict else "ai_confirmed_rule",
        )

    # Quota and hint rules are intentionally conservative.  A high-confidence
    # AI event result is allowed to correct them, while the conflict remains
    # visible for audit and later calibration.
    if ai.category in RESET_EVENT_CATEGORIES and ai.confidence >= 0.85:
        conflict = rule.category != ai.category
        return ClassificationDecision(
            result=ClassificationOutput(
                category=ai.category,
                confidence=ai.confidence,
                urgency=ai.urgency,
                explicitness=ai.explicitness,
                reason=ai.reason if not conflict else (
                    f"AI high-confidence reset event overrides preliminary rule={rule.category}. {ai.reason}"
                ),
            ),
            conflict=conflict,
            reason="ai_reset_event_override" if conflict else "ai_semantic_result",
        )

    conflict = rule.category not in {"unrelated", ai.category}
    confidence = ai.confidence if not conflict else (
        ai.confidence if ai.confidence >= 0.85 else min(rule.confidence, ai.confidence) * 0.8
    )
    reason = ai.reason if not conflict else f"Rule/AI conflict: rule={rule.category}; AI={ai.category}. {ai.reason}"
    return ClassificationDecision(
        result=ClassificationOutput(
            category=ai.category,
            confidence=confidence,
            urgency=ai.urgency,
            explicitness=ai.explicitness,
            reason=reason,
        ),
        conflict=conflict,
        reason="classification_conflict" if conflict else "ai_semantic_result",
    )
