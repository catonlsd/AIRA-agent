# File: backend/app/intent_router.py
"""
Hybrid intent router for AIRA-X.

Routing has two layers:

1. A fast, deterministic keyword classifier (`turn_classifier.classify_turn`).
   When it is confident, we trust it. This keeps obvious turns — greetings,
   explicit tool verbs, artifact requests, explicit document references — free
   and instant.

2. An LLM disambiguation step for the cases the keyword layer is *not*
   confident about (its low-confidence "defaulted to general chat" result).
   Natural phrasing like "I'm stuck on my code, any ideas?" or "commit all my
   changes" cannot be separated by substring matching alone, so we ask the LLM
   to pick one of the known modes.

If no LLM is configured (or it returns something unusable), we fall back to
EXECUTION so the request still flows into the workflow rather than being
silently deflected into a canned chat reply. "When unsure, do the work."
"""

from __future__ import annotations

from typing import Sequence

from app.core.config import settings
from app.core.llm import LLMClient
from app.turn_classifier import (
    DOCUMENT_QA_MODE,
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
    TurnClassification,
    classify_turn,
)

# Below this keyword-confidence, the turn is treated as ambiguous and escalated.
AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.6

VALID_MODES = (
    GENERAL_CHAT_MODE,
    SELF_MEMORY_MODE,
    DOCUMENT_QA_MODE,
    WEB_RESEARCH_MODE,
    EXECUTION_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
)

_LLM_ROUTER_SYSTEM_PROMPT = (
    "You are the intent router for AIRA-X, an AI assistant. "
    "Read the user's message and respond with EXACTLY ONE of these labels, "
    "lowercase, with no punctuation or extra words:\n"
    "- general_chat: greetings, casual conversation, or general knowledge / "
    "daily-life questions you can answer directly without tools.\n"
    "- self_memory: the user asks what you know or remember about them.\n"
    "- document_qa: the question is about an uploaded document or file.\n"
    "- web_research: needs current or external information gathering.\n"
    "- execution: a concrete action to run (commands, files, git, code, installs).\n"
    "- research_then_execution: produce an artifact such as a PPTX, DOCX, or XLSX.\n"
    "Answer with the single best label only."
)


def route_turn(
    prompt: str,
    *,
    has_uploaded_files: bool = False,
    uploaded_file_names: Sequence[str] | None = None,
    llm_client: LLMClient | None = None,
) -> TurnClassification:
    """Return the routed intent for a single prompt using the hybrid strategy."""
    keyword = classify_turn(
        prompt,
        has_uploaded_files=has_uploaded_files,
        uploaded_file_names=uploaded_file_names,
    )

    if keyword.confidence >= AMBIGUOUS_CONFIDENCE_THRESHOLD:
        return keyword

    llm_mode = _classify_with_llm(prompt, llm_client=llm_client)

    if llm_mode in VALID_MODES:
        return _classification_for_mode(
            llm_mode,
            has_uploaded_files=has_uploaded_files,
            source="llm",
        )

    # No usable LLM verdict: route into the workflow rather than deflecting.
    return _classification_for_mode(
        EXECUTION_MODE,
        has_uploaded_files=has_uploaded_files,
        source="fallback",
    )


def _classify_with_llm(prompt: str, *, llm_client: LLMClient | None) -> str | None:
    if not _llm_is_configured():
        return None

    client = llm_client or LLMClient()

    try:
        raw = client.generate(
            system=_LLM_ROUTER_SYSTEM_PROMPT,
            prompt=prompt,
            temperature=0.0,
        )
    except Exception:
        return None

    return _parse_mode(raw)


def _parse_mode(raw: str | None) -> str | None:
    if not raw:
        return None

    normalized = raw.strip().lower()

    # Exact match first, then a tolerant scan for the label inside a sentence.
    if normalized in VALID_MODES:
        return normalized

    for mode in VALID_MODES:
        if mode in normalized:
            return mode

    return None


def _llm_is_configured() -> bool:
    provider = settings.llm_provider

    if provider == "groq":
        return bool(settings.groq_api_key)
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "gemini":
        return bool(settings.gemini_api_key)

    return False


def _classification_for_mode(
    mode: str,
    *,
    has_uploaded_files: bool,
    source: str,
) -> TurnClassification:
    reason = (
        "Resolved by LLM intent disambiguation."
        if source == "llm"
        else "Keyword routing was ambiguous and no LLM verdict was available, "
        "so the turn was routed into the execution workflow."
    )
    confidence = 0.8 if source == "llm" else 0.5

    if mode == GENERAL_CHAT_MODE:
        return TurnClassification(
            mode=GENERAL_CHAT_MODE,
            reason=reason,
            confidence=confidence,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    if mode == SELF_MEMORY_MODE:
        return TurnClassification(
            mode=SELF_MEMORY_MODE,
            reason=reason,
            confidence=confidence,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    if mode == DOCUMENT_QA_MODE:
        return TurnClassification(
            mode=DOCUMENT_QA_MODE,
            reason=reason,
            confidence=confidence,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=True,
            needs_approval_review=False,
            artifact_type=None,
        )

    if mode == WEB_RESEARCH_MODE:
        return TurnClassification(
            mode=WEB_RESEARCH_MODE,
            reason=reason,
            confidence=confidence,
            needs_research=True,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    if mode == RESEARCH_THEN_EXECUTION_MODE:
        return TurnClassification(
            mode=RESEARCH_THEN_EXECUTION_MODE,
            reason=reason,
            confidence=confidence,
            needs_research=True,
            needs_execution=True,
            needs_document_analysis=has_uploaded_files,
            needs_approval_review=True,
            artifact_type=None,
        )

    return TurnClassification(
        mode=EXECUTION_MODE,
        reason=reason,
        confidence=confidence,
        needs_research=False,
        needs_execution=True,
        needs_document_analysis=False,
        needs_approval_review=False,
        artifact_type=None,
    )
