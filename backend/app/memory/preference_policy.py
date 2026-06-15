# File: backend/app/memory/preference_policy.py
"""
Preference write/read/apply policy.

The single place that decides WHAT becomes a remembered preference and HOW saved
preferences influence behaviour. Deliberately conservative and product-minded:

  * Only a fixed catalogue of product-relevant preference KEYS can ever be
    written (answer length/format/style, artifact style, fallback default). It is
    structurally impossible to store arbitrary personal facts here — no names, no
    identity, no sensitive data. That is the anti-creepiness guarantee.
  * A statement is stored only when it reads as a deliberate preference (a clear
    cue like "prefer / always / keep / from now on", or a self-evidently
    preference-shaped phrase). One-off questions never write memory.
  * Saved preferences are applied as DEFAULTS. The applied style directive always
    states that the user's current message overrides saved preferences — the
    current turn wins, never the memory.

Pure functions, no I/O — fully unit-testable.
"""

from __future__ import annotations

import re

# Canonical preference keys + the allowed values. Anything outside this catalogue
# is never stored, so memory can only ever hold product-shaping signals.
ANSWER_LENGTH = "answer_length"        # concise | detailed
ANSWER_FORMAT = "answer_format"        # bullets | prose
ANSWER_STYLE = "answer_style"          # code_first
HEADINGS = "headings"                  # sparse
ARTIFACT_STYLE = "artifact_style"      # clean_professional
FALLBACK_DEFAULT = "fallback_default"  # web

# Cue words that mark a sentence as a deliberate, durable preference (not a
# one-off request). Used by the rules flagged `strong=False`.
_CUES = (
    "prefer", "always", "from now on", "going forward", "i like", "i'd like",
    "i want you to", "please keep", "keep your", "keep answers", "keep responses",
    "make your answers", "make your responses", "default to", "by default",
    "i usually", "in general",
)

# (pattern, key, value, strong). `strong=True` rules are self-evidently
# preference-shaped and fire without a cue; others require a cue word present.
_RULES: tuple[tuple[str, str, str, bool], ...] = (
    (r"\bkeep (?:your |my )?(?:answers?|responses?|replies)\s+(?:short|concise|brief|to the point)\b", ANSWER_LENGTH, "concise", True),
    (r"\b(?:concise|brief|short|succinct)\b.*\b(?:answers?|responses?|replies)\b", ANSWER_LENGTH, "concise", False),
    (r"\b(?:detailed|thorough|in[- ]depth|comprehensive)\b.*\b(?:answers?|responses?|explanations?)\b", ANSWER_LENGTH, "detailed", False),
    (r"\bno bullet points?\b|\bavoid bullet points?\b|\bwithout bullet points?\b|\bin (?:plain )?prose\b|\bin paragraphs?\b", ANSWER_FORMAT, "prose", True),
    (r"\b(?:use |with )?bullet points?\b", ANSWER_FORMAT, "bullets", False),
    (r"\bcode[- ]first\b|\bcode examples? first\b|\bshow (?:me )?(?:the )?code first\b|\blead with code\b", ANSWER_STYLE, "code_first", True),
    (r"\b(?:use )?(?:markdown )?headings?\s+sparingly\b|\bfewer headings\b|\bavoid headings\b", HEADINGS, "sparse", True),
    (r"\b(?:clean|professional|minimal)\b.*\b(?:ppts?|pptx|decks?|slides?|presentations?|reports?|docx|documents?)\b", ARTIFACT_STYLE, "clean_professional", False),
    (r"\b(?:ppts?|pptx|decks?|slides?|presentations?|reports?|docx|documents?)\b.*\b(?:clean|professional|minimal)\b", ARTIFACT_STYLE, "clean_professional", False),
    (r"\bdefault to (?:the )?web\b|\bweb fallback\b.*\b(?:default|insufficient|not enough)\b", FALLBACK_DEFAULT, "web", False),
)

_COMPILED = [(re.compile(p, re.IGNORECASE), k, v, strong) for p, k, v, strong in _RULES]


def extract_preferences(message: str) -> dict[str, str]:
    """Return the deliberate preferences stated in this message (possibly none).

    Conservative: a rule fires only when it is self-evidently a preference, or a
    deliberate-preference cue word is present in the message. One-off questions
    (e.g. "what is a bullet train?") never produce a write.
    """
    text = (message or "").strip()
    if not text:
        return {}
    lowered = text.lower()
    has_cue = any(cue in lowered for cue in _CUES)

    found: dict[str, str] = {}
    for pattern, key, value, strong in _COMPILED:
        if key in found:
            continue
        if not (strong or has_cue):
            continue
        if pattern.search(text):
            found[key] = value
    return found


# Human phrasing for each saved preference (for the style directive + self-memory).
_DESCRIPTIONS: dict[tuple[str, str], str] = {
    (ANSWER_LENGTH, "concise"): "keep answers concise and to the point",
    (ANSWER_LENGTH, "detailed"): "give thorough, detailed answers",
    (ANSWER_FORMAT, "prose"): "answer in prose, avoiding bullet-point lists",
    (ANSWER_FORMAT, "bullets"): "use bullet points where they aid clarity",
    (ANSWER_STYLE, "code_first"): "lead with a code example when the question is technical",
    (HEADINGS, "sparse"): "use markdown headings sparingly",
    (ARTIFACT_STYLE, "clean_professional"): "produce clean, professional artifacts",
    (FALLBACK_DEFAULT, "web"): "fall back to broader web research when uploaded documents are insufficient",
}


def describe_preferences(preferences: dict[str, str]) -> list[str]:
    """Human-readable phrases for stored preferences (catalogue-bounded only)."""
    phrases: list[str] = []
    for key, value in (preferences or {}).items():
        phrase = _DESCRIPTIONS.get((key, str(value)))
        if phrase:
            phrases.append(phrase)
    return phrases


def build_style_directive(preferences: dict[str, str]) -> str:
    """A short system-prompt fragment applying saved answer-style preferences.

    Empty when no relevant preferences are saved. Always ends by stating that the
    current message overrides these defaults, so the current turn wins.
    """
    relevant = {
        k: v for k, v in (preferences or {}).items()
        if k in (ANSWER_LENGTH, ANSWER_FORMAT, ANSWER_STYLE, HEADINGS)
    }
    phrases = describe_preferences(relevant)
    if not phrases:
        return ""
    joined = "; ".join(phrases)
    return (
        "\n\nSaved style preferences for this user (apply as defaults): "
        f"{joined}. If the user's current message asks for a different style, "
        "follow the current message instead — it always takes precedence."
    )


def artifact_style_hint(preferences: dict[str, str]) -> str:
    """One-line artifact style note for the generation context, or empty."""
    if (preferences or {}).get(ARTIFACT_STYLE) == "clean_professional":
        return "Style preference: produce a clean, professional, uncluttered layout."
    return ""


def summarize_for_self_memory(preferences: dict[str, str]) -> str:
    """Honest one-paragraph recap of saved preferences for self-memory answers."""
    phrases = describe_preferences(preferences)
    if not phrases:
        return ""
    return "You've asked me to " + "; ".join(phrases) + "."
