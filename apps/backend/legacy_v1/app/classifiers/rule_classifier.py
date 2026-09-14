from __future__ import annotations

import re

from app.schemas import RuleClassification

from .rules import (
    ANNOUNCEMENT_PATTERNS,
    CODEX_PATTERNS,
    CONFIRMED_PATTERNS,
    DENIAL_PATTERNS,
    HINT_PATTERNS,
    IN_PROGRESS_PATTERNS,
    QUOTA_PATTERNS,
    RESET_RE,
    RESTORED_USAGE_PATTERNS,
    TIME_HINT_PATTERNS,
    TIME_WORD_PATTERNS,
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("’", "'")).strip()


def matched(patterns, text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def classify_rule(text: str, *, is_reply: bool = False) -> RuleClassification:
    """Return a transparent preliminary result using strict priority order."""
    normalized = normalize_text(text)
    has_reset = bool(re.search(RESET_RE, normalized))
    has_time_phrase = matched(TIME_WORD_PATTERNS, normalized)
    has_time_hint = matched(TIME_HINT_PATTERNS, normalized) or bool(
        re.search(r"\b(?:tomorrow|soon|later)\b", normalized)
    )
    has_codex = matched(CODEX_PATTERNS, normalized)
    has_quota = matched(QUOTA_PATTERNS, normalized)

    # Denial must always run before any positive reset rule.
    if matched(DENIAL_PATTERNS, normalized):
        return RuleClassification(
            category="reset_denial",
            confidence=0.99,
            urgency="unknown",
            explicitness="explicit",
            reason="Matched an explicit negation of a reset action.",
            requires_ai=False,
        )

    if matched(CONFIRMED_PATTERNS, normalized):
        return RuleClassification(
            category="reset_confirmed",
            confidence=0.99,
            urgency="now",
            explicitness="explicit",
            reason="Matched language stating that the reset or limits are complete.",
            requires_ai=False,
        )

    if matched(IN_PROGRESS_PATTERNS, normalized):
        return RuleClassification(
            category="reset_in_progress",
            confidence=0.96,
            urgency="now",
            explicitness="explicit",
            reason="Matched language indicating that reset propagation or distribution is underway.",
            requires_ai=False,
        )

    if matched(ANNOUNCEMENT_PATTERNS, normalized):
        urgency = "within_24h" if "tomorrow" in normalized else "within_6h" if any(word in normalized for word in ("today", "tonight")) else "within_3d" if "soon" in normalized else "unknown"
        return RuleClassification(
            category="reset_announcement",
            confidence=0.98,
            urgency=urgency,
            explicitness="explicit",
            reason="Matched an explicit reset announcement pattern.",
            requires_ai=False,
        )

    if matched(RESTORED_USAGE_PATTERNS, normalized):
        return RuleClassification(
            category="reset_confirmed",
            confidence=0.82,
            urgency="now",
            explicitness="explicit",
            reason="Matched reset vocabulary with restored/new usage language; semantic review is required.",
            requires_ai=True,
        )

    has_hint = matched(HINT_PATTERNS, normalized) or (
        has_reset and matched(TIME_HINT_PATTERNS, normalized)
    )
    # A reset/time phrase such as “resets ... soon, but not today” is a hint,
    # not a denial.  Explicit event patterns above have already taken priority.
    has_hint = has_hint or (has_reset and (has_time_hint or has_time_phrase))
    if has_hint:
        urgency = "within_24h" if "tomorrow" in normalized else "within_6h" if "today" in normalized and "not today" not in normalized else "within_3d" if "soon" in normalized else "unknown"
        return RuleClassification(
            category="reset_hint",
            confidence=0.72 if has_time_hint else 0.68,
            urgency=urgency,
            explicitness="implicit",
            reason="Matched a known reset-button or time-linked hint pattern; semantic review is required.",
            requires_ai=True,
        )

    if has_quota:
        ambiguous = has_reset or has_time_phrase or is_reply
        return RuleClassification(
            category="quota_information",
            confidence=0.94 if not ambiguous else 0.78,
            urgency="unknown",
            explicitness="explicit" if not ambiguous else "unclear",
            reason="Matched quota or usage-limit terminology without a confirmed reset action.",
            requires_ai=ambiguous,
        )

    if has_codex:
        ambiguous = has_time_hint or is_reply or has_reset
        return RuleClassification(
            category="codex_related",
            confidence=0.93 if not ambiguous else 0.68,
            urgency="within_24h" if has_time_hint else "unknown",
            explicitness="explicit" if not ambiguous else "unclear",
            reason="Matched Codex-related terminology without a direct reset signal.",
            requires_ai=ambiguous,
        )

    return RuleClassification(
        category="unrelated",
        confidence=0.99,
        urgency="unknown",
        explicitness="explicit",
        reason="No Codex, quota, reset, or known hint signal was found.",
        requires_ai=False,
    )
