# File: backend/app/schemas/assistant_response.py
"""
Frozen request/response contract for the canonical AIRA-X chat turn.

This is the single payload schema the supervisor produces and the route returns.
Everything user-facing (message, mode, sources, artifacts, approvals, meta) is
shaped here so there is exactly one contract to test and one for the frontend
to consume.

Phase 0 contract freeze. Do not add ad-hoc fields in routes; add them here.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ── Top-level routed intents (frozen) ────────────────────────────────────────
GENERAL_CHAT = "general_chat"
SELF_MEMORY = "self_memory"
DOCUMENT_QA = "document_qa"
WEB_RESEARCH = "web_research"
EXECUTION = "execution"
RESEARCH_THEN_EXECUTION = "research_then_execution"
APPROVAL_RESUME = "approval_resume"
MULTI_QUESTION = "multi_question"
CLARIFICATION = "clarification"

TURN_MODES = frozenset(
    {
        GENERAL_CHAT,
        SELF_MEMORY,
        DOCUMENT_QA,
        WEB_RESEARCH,
        EXECUTION,
        RESEARCH_THEN_EXECUTION,
        APPROVAL_RESUME,
        MULTI_QUESTION,
        CLARIFICATION,
    }
)

# ── Turn statuses (frozen) ───────────────────────────────────────────────────
STATUS_COMPLETED = "completed"
STATUS_REQUIRES_APPROVAL = "requires_approval"
STATUS_FAILED = "failed"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"
STATUS_PARTIALLY_COMPLETED = "partially_completed"

TURN_STATUSES = frozenset(
    {
        STATUS_COMPLETED,
        STATUS_REQUIRES_APPROVAL,
        STATUS_FAILED,
        STATUS_NEEDS_CLARIFICATION,
        STATUS_PARTIALLY_COMPLETED,
    }
)


class AssistantTurnRequest(BaseModel):
    """One inbound chat turn.

    `session_id` scopes conversation memory. When absent the supervisor falls
    back to a default session, but the frontend should send a stable id per
    conversation so follow-ups ("continue", "make it shorter") work correctly.
    """

    message: str
    session_id: Optional[str] = None
    # Optional client hints; the supervisor may override based on intent.
    use_web: Optional[bool] = None
    # Approval resume: when set, the turn resumes a paused workflow.
    run_id: Optional[str] = None


class TurnClassificationMeta(BaseModel):
    mode: str
    reason: str = ""
    confidence: float = 0.0
    source: str = "keyword"  # keyword | llm | fallback


class AssistantResponse(BaseModel):
    """The one payload the canonical chat route returns."""

    run_id: str
    session_id: Optional[str] = None
    mode: str
    status: str = STATUS_COMPLETED
    decision: Optional[str] = None

    # Primary user-facing answer. `message` is the short/primary text;
    # `final_answer` is the full composed answer (often identical).
    message: str = ""
    final_answer: Optional[str] = None

    sources: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
    approval_summary: Any | None = None

    # Present only for multi-question turns.
    sub_answers: Optional[list[dict]] = None
    # Present only for execution turns that produced a workflow.
    workflow: Optional[dict] = None

    meta: dict = Field(default_factory=dict)


def is_valid_mode(mode: str) -> bool:
    return mode in TURN_MODES


def is_valid_status(status: str) -> bool:
    return status in TURN_STATUSES
