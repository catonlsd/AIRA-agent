# File: backend/app/assistant_supervisor.py
"""
The canonical turn orchestrator for AIRA-X.

One brain for every chat turn:

    preprocess -> classify -> choose path -> call capability -> compose -> trace

Routes are thin adapters: they build a TurnContext and call `run_turn`. The old
research and execution stacks are invoked here as *capabilities*, not as
separate products.

To avoid an import cycle (routes import the supervisor), the still-shared
helpers that currently live in `app/routes/aira_x.py` are imported lazily inside
methods. Those helpers will migrate into dedicated capability services in later
phases; the supervisor is already the single place that decides routing.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.capabilities.execution.execution_service import ExecutionService
from app.capabilities.research.research_service import ResearchService
from app.context_builder import TurnContext
from app.conversation import generate_conversational_answer
from app.intent_router import route_turn
from app.multi_question_handler import handle_multi_question_prompt
from app.response_composer import compose
from app.schemas.assistant_response import AssistantResponse
from app.turn_classifier import (
    DOCUMENT_QA_MODE,
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
)

MAX_QUESTIONS = 20


class AssistantSupervisor:
    """Routes one chat turn to the right capability and composes the answer."""

    def __init__(self) -> None:
        self.research = ResearchService()
        self.execution = ExecutionService()

    async def run_turn(self, ctx: TurnContext) -> AssistantResponse:
        ctx.trace.event("turn_started", message_len=len(ctx.message))

        result = await handle_multi_question_prompt(
            prompt=ctx.message,
            run_single_prompt=lambda question: self._dispatch(question, ctx),
            max_questions=MAX_QUESTIONS,
        )

        # Single source of normalization for single vs. grouped multi-question.
        from app.routes.aira_x import _normalize_run_response

        normalized = _normalize_run_response(result)
        ctx.trace.event("composed", mode=normalized.get("mode"))

        return compose(normalized, session_id=ctx.session_id, trace=ctx.trace)

    async def _dispatch(self, goal: str, ctx: TurnContext) -> dict[str, Any]:
        classification = route_turn(
            goal,
            has_uploaded_files=ctx.has_uploaded_files,
            uploaded_file_names=ctx.uploaded_file_names,
        )
        ctx.trace.event(
            "classified",
            mode=classification.mode,
            confidence=classification.confidence,
        )

        if classification.mode == GENERAL_CHAT_MODE:
            message = generate_conversational_answer(goal, ctx.history)
            return self._chat_result(goal, classification, message)

        # Lazy import to break the route<->supervisor import cycle.
        from app.routes import aira_x as ax

        if classification.mode == SELF_MEMORY_MODE:
            return ax._build_self_memory_response(goal, classification)

        if classification.mode == DOCUMENT_QA_MODE:
            # Real document-first retrieval lands in the ChromaDB phase; until
            # then this is an honest placeholder.
            return ax._build_document_qa_placeholder_response(goal, classification)

        if classification.mode == WEB_RESEARCH_MODE:
            ctx.trace.event("research_started")
            result = self.research.run(
                goal,
                history=ctx.history,
                preferences=ctx.preferences,
                want_web=True,
                want_documents=False,
                mode=WEB_RESEARCH_MODE,
            )
            ctx.trace.event("research_completed", sources=len(result.get("sources", [])))
            return self._with_classification(result, classification)

        return await self._run_execution(goal, classification, ctx)

    async def _run_execution(self, goal: str, classification, ctx: TurnContext) -> dict[str, Any]:
        ctx.trace.event("execution_started")
        result = await self.execution.run(goal, mode=classification.mode)
        ctx.trace.event("execution_completed", status=result.get("status"))
        return self._with_classification(result, classification)

    @staticmethod
    def _with_classification(result: dict[str, Any], classification) -> dict[str, Any]:
        result.setdefault("meta", {})
        result["meta"]["turn_classification"] = {
            "mode": classification.mode,
            "reason": classification.reason,
            "confidence": classification.confidence,
        }
        return result

    def _chat_result(self, goal: str, classification, message: str) -> dict[str, Any]:
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "general_chat_completed",
            "mode": GENERAL_CHAT_MODE,
            "message": message,
            "final_answer": message,
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": False,
                "has_artifacts": False,
                "requires_approval": False,
                "turn_classification": {
                    "mode": classification.mode,
                    "reason": classification.reason,
                    "confidence": classification.confidence,
                },
            },
        }
