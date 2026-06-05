# File: backend/app/response_composer.py
"""
The one place that shapes a user-facing chat response.

Capabilities (chat, research, execution, ...) return a loose result dict; the
composer normalizes it into the frozen `AssistantResponse` contract so the
assistant feels consistent regardless of which path produced the answer.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from app.schemas.assistant_response import (
    AssistantResponse,
    STATUS_COMPLETED,
)


def compose(
    result: dict[str, Any],
    *,
    session_id: Optional[str] = None,
    trace: Any | None = None,
) -> AssistantResponse:
    """Normalize a capability/handler result dict into the frozen contract."""
    meta = dict(result.get("meta") or {})

    if trace is not None:
        # Attach a compact trace summary; full tracing lands in Phase 4.
        meta.setdefault("trace", trace.as_dict() if hasattr(trace, "as_dict") else trace)

    message = _first_nonempty(
        result.get("message"),
        result.get("final_answer"),
        result.get("answer"),
    )
    final_answer = _first_nonempty(
        result.get("final_answer"),
        result.get("message"),
        result.get("answer"),
    )

    sub_answers = result.get("sub_answers")
    if sub_answers is not None and not isinstance(sub_answers, list):
        sub_answers = None

    return AssistantResponse(
        run_id=str(result.get("run_id") or uuid4().hex),
        session_id=session_id or result.get("session_id"),
        mode=str(result.get("mode") or "general_chat"),
        status=str(result.get("status") or STATUS_COMPLETED),
        decision=result.get("decision"),
        message=message,
        final_answer=final_answer,
        sources=_as_dict_list(result.get("sources")),
        artifacts=_as_dict_list(result.get("artifacts")),
        approval_summary=result.get("approval_summary"),
        sub_answers=sub_answers,
        workflow=result.get("workflow"),
        meta=meta,
    )


def compose_chat(
    *,
    run_id: str,
    mode: str,
    message: str,
    session_id: Optional[str] = None,
    decision: Optional[str] = None,
    classification: Any | None = None,
    trace: Any | None = None,
) -> AssistantResponse:
    """Convenience composer for simple, single-message answers (chat/memory)."""
    meta: dict[str, Any] = {
        "is_multi_question": False,
        "question_count": 1,
        "has_sources": False,
        "has_artifacts": False,
        "requires_approval": False,
    }
    if classification is not None:
        meta["turn_classification"] = {
            "mode": getattr(classification, "mode", mode),
            "reason": getattr(classification, "reason", ""),
            "confidence": getattr(classification, "confidence", 0.0),
        }

    return compose(
        {
            "run_id": run_id,
            "mode": mode,
            "status": STATUS_COMPLETED,
            "decision": decision,
            "message": message,
            "final_answer": message,
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
            "meta": meta,
        },
        session_id=session_id,
        trace=trace,
    )


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
