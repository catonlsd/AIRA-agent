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
from app.conversation import (
    AIRA_X_PERSONA_SYSTEM_PROMPT,
    _build_history_prompt,
    generate_conversational_answer,
    offline_general_chat_message,
)
from app.core.llm import LLMClient
from app.intent_router import route_turn
from app.multi_question_handler import handle_multi_question_prompt
from app.prompt_parsing import parse_prompt_for_questions
from app.response_composer import compose
from app.schemas.assistant_response import AssistantResponse
from app.services.trace_service import TraceService
from app.turn_classifier import (
    CLARIFICATION_MODE,
    DOCUMENT_QA_MODE,
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    WEB_RESEARCH_MODE,
)

MAX_QUESTIONS = 20

# Modes answered directly by the LLM (history-aware), not by a tool/research path.
CONVERSATIONAL_MODES = (GENERAL_CHAT_MODE, SELF_MEMORY_MODE)


class AssistantSupervisor:
    """Routes one chat turn to the right capability and composes the answer."""

    def __init__(self) -> None:
        self.research = ResearchService()
        self.execution = ExecutionService()
        self.tracer = TraceService()
        self._documents = None  # lazily built (constructs a vector-store client)

    def _document_service(self):
        if self._documents is None:
            from app.services.document_qa_service import get_document_qa_service

            self._documents = get_document_qa_service()
        return self._documents

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

        response = compose(normalized, session_id=ctx.session_id, trace=ctx.trace)
        self._persist_trace(ctx, response)
        return response

    async def stream_turn(self, ctx: TurnContext):
        """Stream one turn as SSE-style events: trace, token, source, final, error.

        Single turns stream tokens (real for chat, the composed answer for other
        modes). Multi-question prompts fall back to the non-streaming path and
        emit a single final event. Streamed turns still persist a trace.
        """
        try:
            ctx.trace.event("turn_started", message_len=len(ctx.message))
            yield {"type": "trace", "data": {"event": "turn_started"}}

            if parse_prompt_for_questions(ctx.message).is_multi_question:
                response = await self.run_turn(ctx)
                yield {"type": "final", "data": response.model_dump()}
                return

            classification = route_turn(
                ctx.message,
                has_uploaded_files=ctx.has_uploaded_files,
                uploaded_file_names=ctx.uploaded_file_names,
            )
            ctx.trace.event(
                "classified",
                mode=classification.mode,
                confidence=classification.confidence,
            )
            yield {
                "type": "trace",
                "data": {
                    "event": "classified",
                    "mode": classification.mode,
                    "confidence": classification.confidence,
                },
            }

            if classification.mode in CONVERSATIONAL_MODES:
                chunks: list[str] = []
                for piece in LLMClient().stream(
                    AIRA_X_PERSONA_SYSTEM_PROMPT,
                    _build_history_prompt(ctx.message, ctx.history),
                    temperature=0.7,
                ):
                    if not piece:
                        continue
                    chunks.append(piece)
                    yield {"type": "token", "data": {"text": piece}}
                message = "".join(chunks).strip() or offline_general_chat_message(ctx.message)
                result = self._chat_result(classification, message)
            else:
                result = await self._dispatch_non_chat(ctx.message, classification, ctx)
                for source in result.get("sources", []):
                    yield {"type": "source", "data": source}
                answer = result.get("message") or result.get("final_answer") or ""
                if answer:
                    yield {"type": "token", "data": {"text": answer}}

            from app.routes.aira_x import _normalize_run_response

            normalized = _normalize_run_response(result)
            response = compose(normalized, session_id=ctx.session_id, trace=ctx.trace)
            self._persist_trace(ctx, response)
            yield {"type": "final", "data": response.model_dump()}
        except Exception as error:  # streaming must surface, not crash the socket
            yield {"type": "error", "data": {"message": str(error)}}

    async def _dispatch_non_chat(self, goal: str, classification, ctx: TurnContext) -> dict[str, Any]:
        """Dispatch for every non-conversational mode (research/execution/document)."""
        if classification.mode == CLARIFICATION_MODE:
            # Empty / unintelligible input: ask for clarification rather than
            # running the execution workflow on nothing.
            return self._clarification_result(classification)

        if classification.mode == DOCUMENT_QA_MODE:
            ctx.trace.event("document_qa_started")
            result = self._document_service().answer(goal, history=ctx.history)
            ctx.trace.event(
                "document_qa_completed",
                has_evidence=result.get("meta", {}).get("has_evidence"),
            )
            return self._with_classification(result, classification)

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

        ctx.trace.event("execution_started")
        result = await self.execution.run(goal, mode=classification.mode)
        ctx.trace.event("execution_completed", status=result.get("status"))
        return self._with_classification(result, classification)

    def _persist_trace(self, ctx: TurnContext, response: AssistantResponse) -> None:
        """Best-effort: tracing must never break a turn."""
        try:
            record = self.tracer.build_record(
                session_id=ctx.session_id,
                run_id=response.run_id,
                mode=response.mode,
                latency_ms=ctx.trace.elapsed_ms(),
                final_status=response.status,
                trace_events=ctx.trace.events,
            )
            self.tracer.persist(record)
        except Exception:
            pass

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

        if classification.mode in CONVERSATIONAL_MODES:
            message = generate_conversational_answer(goal, ctx.history)
            return self._chat_result(classification, message)

        return await self._dispatch_non_chat(goal, classification, ctx)

    @staticmethod
    def _with_classification(result: dict[str, Any], classification) -> dict[str, Any]:
        result.setdefault("meta", {})
        result["meta"]["turn_classification"] = {
            "mode": classification.mode,
            "reason": classification.reason,
            "confidence": classification.confidence,
        }
        return result

    def _clarification_result(self, classification) -> dict[str, Any]:
        message = (
            "I didn't quite catch that. Could you rephrase or add a bit more "
            "detail about what you'd like me to help with?"
        )
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "clarification",
            "mode": CLARIFICATION_MODE,
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

    def _chat_result(self, classification, message: str) -> dict[str, Any]:
        decision = (
            "self_memory_completed"
            if classification.mode == SELF_MEMORY_MODE
            else "general_chat_completed"
        )
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": decision,
            "mode": classification.mode,
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
