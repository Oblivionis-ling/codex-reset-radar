"""Transparent, ordered rule fragments for the first-pass classifier.

The patterns intentionally stay narrow.  In particular, a quota phrase is not
treated as a reset event until the text contains an event verb such as
``will land``, ``is rolling out`` or ``has landed``.
"""

import re


# Real posts use both normal and non-standard forms (``reseted``, ``resetted``).
RESET_WORD = r"reset(?:s|ting|ed|ted)?"
RESET_RE = rf"\b{RESET_WORD}\b"

DENIAL_PATTERNS = (
    re.compile(rf"\bno\s+(?:a\s+)?{RESET_WORD}\b"),
    re.compile(rf"\bnot\s+{RESET_WORD}\b"),
    re.compile(rf"\b(?:we|i|they)\s+(?:are|am|is)\s+not\s+{RESET_WORD}\b"),
    re.compile(rf"\b(?:does not|doesn't|do not|don't)\s+{RESET_WORD}\b"),
    re.compile(rf"\b(?:will not|won't|there will not be|there won't be)\s+(?:a\s+)?{RESET_WORD}\b"),
    re.compile(rf"\bno\s+{RESET_WORD}\s+(?:is|was|has been)\s+planned\b"),
)

CONFIRMED_PATTERNS = (
    re.compile(rf"{RESET_RE}\s+(?:is\s+)?(?:complete|completed|done|finished)\b"),
    re.compile(r"\blimits have been reset\b"),
    re.compile(rf"\beveryone should have (?:their|the) limits (?:back|reset)\b"),
    re.compile(r"\byou should have your limits back\b"),
    re.compile(rf"{RESET_WORD}\s+(?:has|have)\s+landed\b"),
    re.compile(rf"{RESET_WORD}\s+(?:has|have|was|were)\s+been\s+(?:propagated|applied|credited|distributed)\b"),
    re.compile(rf"{RESET_WORD}\s+(?:should be|is)\s+available\s+now\b"),
    re.compile(rf"{RESET_WORD}(?:ting)? everyone (?:is )?done\b"),
)

# These indicate a rollout that is underway, rather than a completed event.
IN_PROGRESS_PATTERNS = (
    re.compile(rf"{RESET_RE}\s+in\s+progress\b"),
    re.compile(rf"{RESET_WORD}(?:ting)?\s+now\b"),
    re.compile(rf"\bwe are {RESET_WORD}\b"),
    re.compile(rf"{RESET_RE}\s+(?:is|are)\s+(?:landing|rolling out)\b"),
    re.compile(rf"\b(?:propagating|rolling out|distributing)\b.*{RESET_RE}"),
    re.compile(rf"{RESET_RE}.*\b(?:being propagated|being distributed|rolling out)\b"),
)

# Explicit future reset events.  Keep these after confirmed/in-progress in the
# classifier priority, but before metaphorical hints and generic quota terms.
ANNOUNCEMENT_PATTERNS = (
    re.compile(rf"\b(?:{RESET_WORD})\s+(?:everyone|all users|all limits)\b"),
    re.compile(r"\b(?:hard|full) reset\b"),
    re.compile(rf"{RESET_RE}.*\bwill\s+(?:land|arrive|happen|be\s+(?:there|available))\b"),
    re.compile(rf"\b(?:will|shall|going to)\s+{RESET_WORD}\b"),
    re.compile(rf"{RESET_RE}.*\b(?:scheduled|planned)\b"),
    re.compile(rf"{RESET_RE}.*\b(?:coming soon|scheduled)\b"),
    re.compile(rf"\beveryone gets (?:a\s+)?{RESET_WORD}\b"),
    re.compile(rf"\bwill credit\b.*{RESET_RE}"),
    re.compile(rf"\bcredit every\b.*{RESET_RE}"),
)

# A reset combined with restored/new usage is an event candidate even when the
# author uses a playful or non-standard form.  It remains AI-reviewable.
RESTORED_USAGE_PATTERNS = (
    re.compile(rf"{RESET_RE}.*\b(?:brand new|new|restored|back)\b.*\busage\b"),
    re.compile(r"\b(?:brand new|new|restored|back)\b.*\busage\b.*\bbutton\s+press\b"),
)

QUOTA_PATTERNS = (
    re.compile(r"\busage limits?\b"),
    re.compile(r"\bquota\b"),
    re.compile(r"\badditional usage\b"),
    re.compile(r"\b\d+x limits?\b"),
    re.compile(r"\b\d+\s*h(?:our)?\s+limits?\b"),
    re.compile(r"\bmore limits\b"),
    re.compile(r"\brate limits?\b"),
    re.compile(r"\bweekly limits?\b"),
    re.compile(rf"\bbanked\s+{RESET_WORD}\b"),
    re.compile(rf"\b{RESET_WORD}\s+credits?\b"),
)

CODEX_PATTERNS = (
    re.compile(r"\bcodex\b"),
    re.compile(r"\bchatgpt coding\b"),
    re.compile(r"\bcoding agent\b"),
    re.compile(r"\bcodex cli\b"),
    re.compile(r"\bcodex app\b"),
)

HINT_PATTERNS = (
    re.compile(rf"{RESET_RE}\s+button\b"),
    re.compile(r"\b(?:push|press|find) the button\b"),
    re.compile(r"\bbutton\s+press\b"),
    re.compile(r"\bdust(?:\s+it|\s+off|\s+that|\s+the button)(?:\s+(?:off|up))?\b"),
    re.compile(rf"\bgift\b.*\b(?:everyone|tomorrow|limits?|{RESET_WORD})\b"),
    re.compile(rf"\bsurprise\b.*\b(?:everyone|tomorrow|limits?|{RESET_WORD})\b"),
)

TIME_HINT_PATTERNS = (
    re.compile(rf"\btomorrow\b.*\b(?:button|limits?|{RESET_WORD})\b"),
    re.compile(rf"\b(?:button|limits?|{RESET_WORD})\b.*\btomorrow\b"),
    re.compile(rf"\b(?:soon|later|today|tonight)\b.*\b(?:button|limits?|{RESET_WORD})\b"),
    re.compile(rf"\b(?:button|limits?|{RESET_WORD})\b.*\b(?:soon|later|today|tonight)\b"),
)

TIME_WORD_PATTERNS = (
    re.compile(r"\b(?:today|tonight|tomorrow|soon|later)\b"),
    re.compile(r"\b(?:by|around)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b"),
    re.compile(r"\bwithin\s+(?:a few hours|\d+\s+hours?)\b"),
)
