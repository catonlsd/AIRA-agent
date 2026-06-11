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
from app.multi_question_handler import handle_multi_question_prompt
from app.supervisor_reasoning import (
    CAP_DOCUMENT_QA,
    CAP_WEB_RESEARCH,
    TurnReasoning,
    reason_about_turn,
)
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


def _stage_for_mode(mode: str, reasoning: TurnReasoning | None) -> str | None:
    """Workflow-intelligence stage name announced before dispatch (2A.6)."""
    if reasoning is not None and reasoning.needs_clarification:
        return "clarifying"
    if reasoning is not None and reasoning.capabilities == [
        CAP_DOCUMENT_QA,
        CAP_WEB_RESEARCH,
    ]:
        return "reading_documents"
    return {
        DOCUMENT_QA_MODE: "reading_documents",
        WEB_RESEARCH_MODE: "collecting_sources",
        EXECUTION_MODE: "executing_workflow",
        RESEARCH_THEN_EXECUTION_MODE: "researching",
    }.get(mode)


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

            reasoning = reason_about_turn(
                ctx.message,
                history=ctx.history,
                has_uploaded_files=ctx.has_uploaded_files,
                uploaded_file_names=ctx.uploaded_file_names,
            )
            classification = reasoning.classification
            ctx.trace.event(
                "classified",
                mode=classification.mode,
                confidence=classification.confidence,
            )
            ctx.trace.event("reasoned", **reasoning.trace_fields())
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
                # Workflow intelligence: surface the stage before dispatching.
                stage = _stage_for_mode(classification.mode, reasoning)
                if stage:
                    yield {"type": "trace", "data": {"event": "stage", "stage": stage}}
                result = await self._dispatch_non_chat(
                    ctx.message, classification, ctx, reasoning=reasoning
                )
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

    async def _dispatch_non_chat(
        self,
        goal: str,
        classification,
        ctx: TurnContext,
        reasoning: TurnReasoning | None = None,
    ) -> dict[str, Any]:
        """Dispatch for every non-conversational mode (research/execution/document)."""
        if classification.mode == CLARIFICATION_MODE:
            # Empty / unintelligible input: ask for clarification rather than
            # running the execution workflow on nothing.
            return self._clarification_result(classification)

        # Clarification intelligence: the request is routed to an action but is
        # genuinely under-specified — ask targeted questions instead of guessing.
        if reasoning is not None and reasoning.needs_clarification:
            ctx.trace.event(
                "clarification_requested",
                questions=reasoning.clarification_questions,
            )
            return self._targeted_clarification_result(
                classification, reasoning.clarification_questions
            )

        # Capability composition: the question spans documents AND the web.
        if reasoning is not None and reasoning.capabilities == [
            CAP_DOCUMENT_QA,
            CAP_WEB_RESEARCH,
        ]:
            return await self._compose_document_and_research(goal, classification, ctx)

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

    async def _compose_document_and_research(
        self, goal: str, classification, ctx: TurnContext
    ) -> dict[str, Any]:
        """Capability composition: answer from documents AND the web, then merge.

        Both capabilities run with their normal services; a final synthesis call
        combines the two grounded answers. Sources from both are preserved.
        """
        ctx.trace.event("stage", stage="reading_documents")
        doc_result = self._document_service().answer(goal, history=ctx.history)
        doc_answer = (doc_result.get("message") or doc_result.get("final_answer") or "").strip()

        ctx.trace.event("stage", stage="collecting_sources")
        research_result = self.research.run(
            goal,
            history=ctx.history,
            preferences=ctx.preferences,
            want_web=True,
            want_documents=False,
            mode=WEB_RESEARCH_MODE,
        )
        research_answer = (
            research_result.get("message") or research_result.get("final_answer") or ""
        ).strip()

        ctx.trace.event("stage", stage="comparing_findings")
        combined = self._synthesize_composed_answer(goal, doc_answer, research_answer)

        ctx.trace.event("stage", stage="generating_answer")
        sources = list(doc_result.get("sources", [])) + list(
            research_result.get("sources", [])
        )
        result = {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "composed_answer",
            "mode": classification.mode,
            "message": combined,
            "final_answer": combined,
            "sources": sources,
            "artifacts": [],
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": bool(sources),
                "has_artifacts": False,
                "requires_approval": False,
                "capabilities_used": [CAP_DOCUMENT_QA, CAP_WEB_RESEARCH],
            },
        }
        return self._with_classification(result, classification)

    @staticmethod
    def _synthesize_composed_answer(goal: str, doc_answer: str, research_answer: str) -> str:
        """Merge the document-grounded and web-grounded answers into one reply."""
        if not doc_answer and not research_answer:
            return (
                "I couldn't find enough material in your documents or from research "
                "to answer that. Could you add more detail or upload the relevant file?"
            )
        if not doc_answer:
            return research_answer
        if not research_answer:
            return doc_answer
        try:
            merged = LLMClient().generate(
                system=(
                    "You are AIRA-X. Combine the two grounded answers below into one "
                    "clear, well-structured reply to the user's request. Draw on both: "
                    "what their documents say and what external research says. Note "
                    "agreements and differences where relevant. Do not invent facts "
                    "beyond the two answers. No headings about 'Answer 1/2' — write "
                    "one natural reply."
                ),
                prompt=(
                    f"User request: {goal}\n\n"
                    f"Answer grounded in the user's documents:\n{doc_answer}\n\n"
                    f"Answer grounded in web research:\n{research_answer}"
                ),
                temperature=0.3,
            ).strip()
            if merged:
                return merged
        except Exception:
            pass
        # Offline fallback: present both groundings without an LLM merge.
        return (
            f"From your documents:\n{doc_answer}\n\n"
            f"From recent research:\n{research_answer}"
        )

    def _targeted_clarification_result(
        self, classification, questions: list[str]
    ) -> dict[str, Any]:
        bullets = "\n".join(f"- {question}" for question in questions)
        message = (
            "Happy to help — a couple of quick details first so I get it right:\n"
            f"{bullets}"
        )
        result = self._clarification_result(classification)
        result["message"] = message
        result["final_answer"] = message
        result["meta"]["clarification_questions"] = questions
        return result

    def _persist_trace(self, ctx: TurnContext, response: AssistantResponse) -> None:
        """Best-effort: tracing must never break a turn."""
        try:
            reasoned = next(
                (
                    event
                    for event in ctx.trace.events
                    if event.get("name") == "reasoned"
                ),
                {},
            )
            record = self.tracer.build_record(
                session_id=ctx.session_id,
                run_id=response.run_id,
                mode=response.mode,
                latency_ms=ctx.trace.elapsed_ms(),
                final_status=response.status,
                trace_events=ctx.trace.events,
                conversation_type=reasoned.get("conversation_type"),
                selected_route=reasoned.get("selected_route"),
                candidate_routes=reasoned.get("candidate_routes"),
                confidence=reasoned.get("confidence"),
                clarification_needed=reasoned.get("clarification_needed"),
                capabilities_used=reasoned.get("capabilities_used"),
            )
            self.tracer.persist(record)
        except Exception:
            pass

    async def _dispatch(self, goal: str, ctx: TurnContext) -> dict[str, Any]:
        reasoning = reason_about_turn(
            goal,
            history=ctx.history,
            has_uploaded_files=ctx.has_uploaded_files,
            uploaded_file_names=ctx.uploaded_file_names,
        )
        classification = reasoning.classification
        ctx.trace.event(
            "classified",
            mode=classification.mode,
            confidence=classification.confidence,
        )
        ctx.trace.event("reasoned", **reasoning.trace_fields())

        if classification.mode in CONVERSATIONAL_MODES:
            message = generate_conversational_answer(goal, ctx.history)
            return self._chat_result(classification, message)

        return await self._dispatch_non_chat(goal, classification, ctx, reasoning=reasoning)

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
