# File: backend/app/supervisor_reasoning.py
"""
Supervisor reasoning layer (Phase 2A).

A lightweight, deterministic pre-dispatch step that turns "which keyword
matched" into an explicit routing decision:

    intent (route)            -> from the hybrid intent router (unchanged)
    conversation relationship -> CONTINUATION | FOLLOW_UP | NEW_TOPIC
    candidate route scores    -> deterministic confidence per route
    clarification check       -> targeted questions for genuinely vague asks
    capability plan           -> one capability, or a composition of several

It is intentionally NOT chain-of-thought: no extra LLM calls are made here, no
internal reasoning is exposed to users. The output feeds routing decisions and
the trace record only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from app.conversation import classify_memory_use
from app.intent_router import route_turn
from app.turn_classifier import (
    DOCUMENT_QA_MODE,
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
    TurnClassification,
    _has_explicit_document_reference,
    _is_execution_request,
    _is_research_request,
    _normalize_text,
)

# Conversation relationship labels (Phase 2A.1).
CONTINUATION = "CONTINUATION"
FOLLOW_UP = "FOLLOW_UP"
NEW_TOPIC = "NEW_TOPIC"

# Capabilities the supervisor can select individually or compose (2A.3).
CAP_CHAT = "chat"
CAP_MEMORY = "memory"
CAP_DOCUMENT_QA = "document_qa"
CAP_WEB_RESEARCH = "web_research"
CAP_EXECUTION = "execution"

# Candidate scores closer than this are considered "close" (2A.4).
CLOSE_CONFIDENCE_MARGIN = 0.1

# Signals that the user wants fresh/external information alongside documents.
_RESEARCH_SIGNAL_PATTERN = re.compile(
    r"\b(recent|latest|current|new(est)?|up[- ]to[- ]date|today|web|online|"
    r"internet|news|research|published|state of the art)\b"
)

# First-word verbs that can start a genuinely under-specified request (2A.2).
_VAGUE_BUILD_VERBS = (
    "build", "create", "make", "develop", "design", "implement", "write",
)
_VAGUE_DEPLOY_VERBS = (
    "deploy", "publish", "release", "migrate", "ship", "host",
)
_SETUP_PREFIXES = ("set up", "setup")

# Tokens that indicate the user already supplied specifics (so do NOT ask).
_SPECIFIER_TOKENS = re.compile(
    r"\b(about|for|with|using|from|into|onto|to|on|at|in|of|named|called|titled|"
    r"based|via|like)\b"
)
# Anything file-ish, quoted, or numeric counts as a concrete detail.
_CONCRETE_TOKEN = re.compile(r"[\"'`]|\d|[\w-]+\.[A-Za-z]{1,4}\b|[/\\]")
# Multi-step phrasing belongs to composition, not clarification.
_MULTI_STEP = re.compile(r"\b(and|then|after that)\b")

_CLARIFY_MAX_WORDS = 8

_DEPLOY_QUESTIONS = [
    "Which application or project should I work with?",
    "Where should it go (cloud provider, server, or container)?",
]
_BUILD_QUESTIONS = [
    "What should it be built with (stack, tools, or format)?",
    "Any constraints I should know about (scale, environment, or data)?",
]
_GENERIC_QUESTIONS = [
    "Could you add a bit more detail about the goal and any constraints?",
]


@dataclass
class TurnReasoning:
    """The supervisor's pre-dispatch decision record (internal only)."""

    classification: TurnClassification
    conversation_type: str = NEW_TOPIC
    candidate_routes: dict[str, float] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)

    @property
    def selected_route(self) -> str:
        return self.classification.mode

    @property
    def confidence(self) -> float:
        return self.classification.confidence

    def trace_fields(self) -> dict:
        """The (non-sensitive) fields persisted into the turn trace (2A.7)."""
        return {
            "conversation_type": self.conversation_type,
            "selected_route": self.selected_route,
            "candidate_routes": self.candidate_routes,
            "confidence": self.confidence,
            "clarification_needed": self.needs_clarification,
            "capabilities_used": self.capabilities,
        }


def classify_conversation_type(message: str, history: Sequence[dict] | None) -> str:
    """Map the memory classifier onto the three supervisor relationship labels."""
    kind = classify_memory_use(message, history)
    if kind == "continuation":
        return CONTINUATION
    if kind in ("follow_up", "explicit_recall"):
        return FOLLOW_UP
    return NEW_TOPIC


def score_candidate_routes(
    message: str,
    classification: TurnClassification,
    *,
    has_uploaded_files: bool = False,
) -> dict[str, float]:
    """Deterministic per-route confidence candidates (2A.4).

    The selected route keeps the router's own confidence as a floor; the other
    routes are scored from the same keyword signals the classifier uses, so the
    trace shows *how close* the decision was without extra LLM calls.
    """
    text = _normalize_text(message)

    doc_ref = _has_explicit_document_reference(text, None)
    research_hits = len(_RESEARCH_SIGNAL_PATTERN.findall(text))
    execution_hit = _is_execution_request(text) or text.startswith(_SETUP_PREFIXES)

    scores = {
        DOCUMENT_QA_MODE: 0.1
        + (0.45 if doc_ref else 0.0)
        + (0.25 if has_uploaded_files else 0.0),
        WEB_RESEARCH_MODE: 0.1
        + min(research_hits, 3) * 0.2
        + (0.25 if _is_research_request(text) else 0.0),
        EXECUTION_MODE: 0.1 + (0.5 if execution_hit else 0.0),
        GENERAL_CHAT_MODE: 0.3 if not (doc_ref or execution_hit) else 0.1,
    }

    selected = classification.mode
    scores[selected] = max(scores.get(selected, 0.0), classification.confidence)

    return {mode: round(min(score, 0.98), 2) for mode, score in scores.items()}


def plan_capabilities(
    message: str,
    classification: TurnClassification,
    *,
    has_uploaded_files: bool = False,
) -> list[str]:
    """Select the capability set for this turn — one, or a composition (2A.3)."""
    text = _normalize_text(message)

    doc_signal = (
        classification.mode == DOCUMENT_QA_MODE
        or _has_explicit_document_reference(text, None)
        or (has_uploaded_files and "document" in text)
    )
    research_signal = (
        classification.mode == WEB_RESEARCH_MODE
        or bool(_RESEARCH_SIGNAL_PATTERN.search(text))
        or _is_research_request(text)
    )

    # Document + web composition: the question spans both knowledge sources.
    if doc_signal and research_signal and classification.mode in (
        DOCUMENT_QA_MODE,
        WEB_RESEARCH_MODE,
    ):
        return [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH]

    if classification.mode == RESEARCH_THEN_EXECUTION_MODE:
        return [CAP_WEB_RESEARCH, CAP_EXECUTION]
    if classification.mode == DOCUMENT_QA_MODE:
        return [CAP_DOCUMENT_QA]
    if classification.mode == WEB_RESEARCH_MODE:
        return [CAP_WEB_RESEARCH]
    if classification.mode == EXECUTION_MODE:
        return [CAP_EXECUTION]
    if classification.mode == SELF_MEMORY_MODE:
        return [CAP_MEMORY]
    return [CAP_CHAT]


def assess_clarification(
    message: str,
    classification: TurnClassification,
) -> tuple[bool, list[str]]:
    """Detect genuinely under-specified action requests (2A.2).

    Deliberately conservative: only short, action-routed messages with no
    specifics at all trigger questions. Anything carrying a target ("about X",
    a filename, a destination, quotes, numbers) is treated as clear intent.
    """
    if classification.mode not in (EXECUTION_MODE, RESEARCH_THEN_EXECUTION_MODE):
        return False, []

    text = _normalize_text(message)
    words = text.split()
    if not words or len(words) > _CLARIFY_MAX_WORDS:
        return False, []

    first = words[0]
    is_vague_verb = first in _VAGUE_BUILD_VERBS or first in _VAGUE_DEPLOY_VERBS
    if not is_vague_verb and not text.startswith(_SETUP_PREFIXES):
        return False, []

    if _SPECIFIER_TOKENS.search(text):
        return False, []
    if _CONCRETE_TOKEN.search(message):
        return False, []
    if _MULTI_STEP.search(text):
        return False, []

    if first in _VAGUE_DEPLOY_VERBS:
        return True, list(_DEPLOY_QUESTIONS)
    if is_vague_verb or text.startswith(_SETUP_PREFIXES):
        return True, list(_BUILD_QUESTIONS)
    return True, list(_GENERIC_QUESTIONS)


def reason_about_turn(
    message: str,
    *,
    history: Sequence[dict] | None = None,
    has_uploaded_files: bool = False,
    uploaded_file_names: Sequence[str] | None = None,
) -> TurnReasoning:
    """The supervisor's explicit pre-dispatch reasoning step (2A.5).

    Runs the existing hybrid router, then layers on conversation relationship,
    candidate scoring, composition planning, and the clarification check.
    Lightweight by design: at most the one LLM call the router already made.
    """
    classification = route_turn(
        message,
        has_uploaded_files=has_uploaded_files,
        uploaded_file_names=uploaded_file_names,
    )

    conversation_type = classify_conversation_type(message, history)
    candidates = score_candidate_routes(
        message, classification, has_uploaded_files=has_uploaded_files
    )
    capabilities = plan_capabilities(
        message, classification, has_uploaded_files=has_uploaded_files
    )
    needs_clarification, questions = assess_clarification(message, classification)

    # Close-call handling (2A.4): when the top two candidates are nearly tied
    # and they are the two knowledge sources, prefer composition over guessing.
    ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    if (
        not needs_clarification
        and len(ranked) >= 2
        and ranked[0][1] - ranked[1][1] <= CLOSE_CONFIDENCE_MARGIN
        and {ranked[0][0], ranked[1][0]} == {DOCUMENT_QA_MODE, WEB_RESEARCH_MODE}
        and classification.mode in (DOCUMENT_QA_MODE, WEB_RESEARCH_MODE)
        and capabilities != [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH]
    ):
        capabilities = [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH]

    return TurnReasoning(
        classification=classification,
        conversation_type=conversation_type,
        candidate_routes=candidates,
        capabilities=capabilities,
        needs_clarification=needs_clarification,
        clarification_questions=questions,
    )
