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

from app.artifacts.service import ArtifactService, PendingArtifact, artifact_store
from app.capabilities.execution.execution_service import ExecutionService
from app.capabilities.research.research_service import ResearchService
from app.clarification import (
    ClarificationSelection,
    PendingAction,
    PendingClarification,
    PendingPlan,
    action_store,
    build_continuation_goal,
    clarification_store,
    generate_plan_steps,
    option_groups_for,
    parse_plan_decision,
    parse_selection,
    plan_store,
    render_clarification_message,
    render_plan_message,
    resolved_task_from,
    structured_clarification,
)
from app.context_builder import TurnContext
from app.core.llm import LLMClient
from app.core.config import settings
from app.llm_answer_service import DirectAnswerService
from app.memory import preference_policy
from app.memory.preference_memory import preference_memory
from app.memory.session_memory import session_memory
from app.multi_question_handler import handle_multi_question_prompt
from app.plan_executor import (
    ExecutablePlan,
    build_executable_plan,
    build_runtime_actions,
    execute_plan,
    execute_runtime_validation,
    render_execution_report,
    render_runtime_offer,
    render_runtime_report,
)
from app.supervisor_reasoning import (
    CAP_DOCUMENT_QA,
    CAP_WEB_RESEARCH,
    TurnReasoning,
    reason_about_turn,
)
from app.usage_limits import (
    KIND_ARTIFACT,
    KIND_EXECUTION,
    KIND_STARTUP,
    quota_service,
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

import json
import logging
import re

# Operational lifecycle log (ops-facing, never shown in the chat UI). One
# structured line per significant supervisor event, correlated by
# session_id/run_id so deployments can grep a full turn end-to-end.
_ops_logger = logging.getLogger("aira_x.supervisor")


def _ops_log(event: str, ctx, **fields) -> None:
    try:
        payload = {
            "event": event,
            "session_id": getattr(ctx, "session_id", None),
            "turn_id": getattr(getattr(ctx, "trace", None), "turn_id", None),
            **fields,
        }
        _ops_logger.info(json.dumps(payload, default=str))
    except Exception:
        pass


MAX_QUESTIONS = 20

# Modes answered directly by the LLM (history-aware), not by a tool/research path.
CONVERSATIONAL_MODES = (GENERAL_CHAT_MODE, SELF_MEMORY_MODE)

# A follow-up that revises the last artifact ("add more content / images",
# "make every slide longer") — needs both an edit verb and an artifact-ish noun,
# so a fresh, unrelated request never trips it.
_REVISION_VERB = re.compile(
    r"\b(add|increase|include|expand|elaborate|make|more|redo|regenerate|improve|lengthen|enrich|put|give)\b",
    re.IGNORECASE,
)
_REVISION_NOUN = re.compile(
    r"\b(content|detail|details|slide|slides|image|images|picture|pictures|deck|"
    r"presentation|ppt|pptx|document|report|paragraph|paragraphs|longer|each|every)\b",
    re.IGNORECASE,
)
# The honest sentinel the execution planner emits when it can't find an action.
_NOOP_EXECUTION_SENTINEL = "specific executable action"


def _is_artifact_revision(goal: str) -> bool:
    text = goal or ""
    return bool(_REVISION_VERB.search(text) and _REVISION_NOUN.search(text))


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
        self.answers = DirectAnswerService()
        self.artifacts = ArtifactService()
        self.tracer = TraceService()
        self._documents = None  # lazily built (constructs a vector-store client)

    def _document_service(self):
        if self._documents is None:
            from app.services.document_qa_service import get_document_qa_service

            self._documents = get_document_qa_service()
        return self._documents

    def _prime_memory(self, ctx: TurnContext) -> None:
        """Load owner-scoped preference memory and capture any newly-stated ones.

        Write policy: only deliberate, catalogue preferences are persisted (see
        preference_policy) — never arbitrary personal facts. Read policy: saved
        preferences become defaults on ctx.preferences; the current turn's
        explicit instructions still win at answer time. Working context is noted
        ephemerally to session memory and is never auto-promoted. Memory must
        never break a turn, so this degrades silently on any error.
        """
        try:
            owner = ctx.owner
            stated = preference_policy.extract_preferences(ctx.message)
            if stated:
                preference_memory.set_many(owner, stated, source="stated_in_chat")
                ctx.trace.event("preferences_remembered", keys=sorted(stated.keys()))
            saved = preference_memory.get(owner)
            if saved:
                # Owner-scoped saved preferences take precedence over legacy globals.
                ctx.preferences = {**(ctx.preferences or {}), **saved}
            session_memory.note(owner, ctx.session_id, "last_request", ctx.message[:200])
        except Exception:
            pass

    async def run_turn(self, ctx: TurnContext) -> AssistantResponse:
        ctx.trace.event("turn_started", message_len=len(ctx.message))
        self._prime_memory(ctx)

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
            self._prime_memory(ctx)
            yield {"type": "trace", "data": {"event": "turn_started"}}

            if parse_prompt_for_questions(ctx.message).is_multi_question:
                response = await self.run_turn(ctx)
                yield {"type": "final", "data": response.model_dump()}
                return

            # Pending guided flows: runtime actions, then a plan awaiting
            # approval, then a clarification whose answer resumes the task.
            guided_result: dict[str, Any] | None = None
            pending_artifact = artifact_store.get(ctx.owner)
            if pending_artifact is not None:
                guided_result = await self._handle_artifact_reply(
                    ctx.message, pending_artifact, ctx
                )
            pending_action = action_store.get(ctx.owner) if guided_result is None else None
            if pending_action is not None:
                guided_result = await self._handle_action_reply(
                    ctx.message, pending_action, ctx
                )
            if guided_result is None:
                plan = plan_store.get(ctx.owner)
                if plan is not None:
                    guided_result = await self._handle_plan_reply(ctx.message, plan, ctx)
            if guided_result is None:
                pending = clarification_store.get(ctx.owner)
                if pending is not None:
                    selection = parse_selection(ctx.message, pending)
                    if selection is not None:
                        guided_result = await self._resume_after_clarification(
                            ctx.message, pending, selection, ctx
                        )
            if guided_result is not None:
                for source in guided_result.get("sources", []):
                    yield {"type": "source", "data": source}
                answer = guided_result.get("message") or guided_result.get("final_answer") or ""
                if answer:
                    yield {"type": "token", "data": {"text": answer}}
                from app.routes.aira_x import _normalize_run_response

                normalized = _normalize_run_response(guided_result)
                response = compose(normalized, session_id=ctx.session_id, trace=ctx.trace)
                self._persist_trace(ctx, response)
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
                # Direct-answer path: streamed straight from the answer
                # service — no tools, no workflow noise.
                chunks: list[str] = []
                for piece in self.answers.stream(
                    ctx.message,
                    mode=classification.mode,
                    history=ctx.history,
                    preferences=ctx.preferences,
                ):
                    chunks.append(piece)
                    yield {"type": "token", "data": {"text": piece}}
                message = "".join(chunks).strip() or self.answers.fallback(
                    ctx.message, mode=classification.mode, history=ctx.history
                )
                result = self._chat_result(classification, message)
            else:
                # Workflow intelligence: surface the stage before dispatching.
                stage = _stage_for_mode(classification.mode, reasoning)
                last_stage = stage
                if stage:
                    yield {"type": "trace", "data": {"event": "stage", "stage": stage}}
                # Replay the real phase sequence recorded during dispatch as live
                # `stage` events (planning → executing → validating → starting_app
                # → readiness → healthcheck → repairing → …). These are truthful:
                # the phases actually ran, in this order — we surface what was
                # previously only written to the trace. Consecutive duplicates are
                # collapsed so the UI never flickers.
                trace_mark = len(ctx.trace.events)
                result = await self._dispatch_non_chat(
                    ctx.message, classification, ctx, reasoning=reasoning
                )
                for recorded in ctx.trace.events[trace_mark:]:
                    if recorded.get("name") != "stage":
                        continue
                    stage_name = recorded.get("stage")
                    if not stage_name or stage_name == last_stage:
                        continue
                    last_stage = stage_name
                    yield {"type": "trace", "data": {"event": "stage", "stage": stage_name}}
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
        # genuinely under-specified — present guided options (or targeted
        # questions) and remember the request so the next reply continues it.
        if reasoning is not None and reasoning.needs_clarification:
            ctx.trace.event(
                "clarification_requested",
                questions=reasoning.clarification_questions,
            )
            return self._present_clarification(
                goal, classification, reasoning.clarification_questions, ctx
            )

        # Artifact requests (PPTX/DOCX/XLSX): prepare structured content, then
        # present a plan to approve before generating the real file. Runs
        # through the same plan -> approve -> generate -> validate model as code.
        if getattr(classification, "artifact_type", None):
            return self._present_artifact_plan(
                goal, classification, classification.artifact_type, ctx
            )

        # Follow-up that revises the artifact we just made ("add more content /
        # images", "make every slide longer") -> regenerate a richer version
        # through the same artifact pipeline, instead of generic execution.
        revision = self._artifact_revision_request(goal, ctx)
        if revision is not None:
            return self._present_artifact_plan(
                revision["goal"], classification, revision["kind"], ctx
            )

        # Capability composition: the question spans documents AND the web.
        if reasoning is not None and reasoning.capabilities == [
            CAP_DOCUMENT_QA,
            CAP_WEB_RESEARCH,
        ]:
            return await self._compose_document_and_research(goal, classification, ctx)

        if classification.mode == DOCUMENT_QA_MODE:
            # Document-first: answer from the uploaded files when the evidence
            # supports it; otherwise say so honestly and escalate to broader
            # research, clearly marked. Vector internals stay in meta/traces.
            ctx.trace.event("document_qa_started")
            result = self._document_service().answer(goal, history=ctx.history, owner=ctx.owner)
            has_evidence = result.get("meta", {}).get("has_evidence")
            ctx.trace.event("document_qa_completed", has_evidence=has_evidence)

            result.setdefault("meta", {})
            if has_evidence is False:
                ctx.trace.event("stage", stage="document_fallback_research")
                try:
                    research = self.research.run(
                        goal,
                        history=ctx.history,
                        preferences=ctx.preferences,
                        want_web=True,
                        want_documents=False,
                        mode=WEB_RESEARCH_MODE,
                    )
                except Exception:
                    research = {}
                answer = (
                    research.get("message") or research.get("final_answer") or ""
                ).strip()
                if answer:
                    notice = (
                        "Your uploaded documents don't appear to contain enough "
                        "information to answer that directly, so here's what "
                        "broader research says:"
                    )
                    result["message"] = f"{notice}\n\n{answer}"
                    result["final_answer"] = result["message"]
                    result["sources"] = list(research.get("sources", []))
                    result["decision"] = "document_qa_web_fallback"
                    result["meta"]["answered_from"] = "web_fallback"
                    result["meta"]["has_sources"] = bool(result["sources"])
                else:
                    # No usable fallback: keep the honest insufficiency reply.
                    result["meta"]["answered_from"] = "insufficient_documents"
            else:
                result["meta"]["answered_from"] = "uploaded_documents"
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
        # The execution planner couldn't find a concrete action: report that
        # honestly as a clarification, NOT as a completed workflow (no fake
        # "Execution complete" when nothing actually ran).
        if self._is_noop_execution(result):
            ctx.trace.event("execution_noop")
            return self._needs_action_result(classification)
        return self._with_classification(result, classification)

    @staticmethod
    def _is_noop_execution(result: dict[str, Any]) -> bool:
        text = (result.get("final_answer") or result.get("message") or "").lower()
        return _NOOP_EXECUTION_SENTINEL in text

    def _artifact_revision_request(self, goal: str, ctx: TurnContext) -> dict[str, Any] | None:
        """If this is a revision of the artifact we just made, build a richer
        regeneration goal for the same kind. Returns None when it isn't one."""
        last = session_memory.value(ctx.owner, ctx.session_id, "last_artifact")
        if not isinstance(last, dict) or not last.get("kind"):
            return None
        if not _is_artifact_revision(goal):
            return None
        base = (last.get("goal") or last.get("title") or "").strip()
        combined = (
            f"{base}. Apply this revision: {goal.strip()}. Produce richer, more "
            "detailed content for every slide/section and include relevant images."
        )
        ctx.trace.event("artifact_revision", kind=last["kind"])
        return {"goal": combined, "kind": last["kind"]}

    def _needs_action_result(self, classification) -> dict[str, Any]:
        message = (
            "I couldn't pin down a concrete action for that. If you meant to revise "
            "something I just created — like a presentation or document — tell me "
            "what to change (e.g. “add more detail to each slide and include images”). "
            "Otherwise, ask me to run a specific command, run code, or work with a file."
        )
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "needs_action_clarification",
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
                    "reason": getattr(classification, "reason", ""),
                    "confidence": getattr(classification, "confidence", ""),
                },
            },
        }

    async def _compose_document_and_research(
        self, goal: str, classification, ctx: TurnContext
    ) -> dict[str, Any]:
        """Capability composition: answer from documents AND the web, then merge.

        Both capabilities run with their normal services; a final synthesis call
        combines the two grounded answers. Sources from both are preserved.
        """
        ctx.trace.event("stage", stage="reading_documents")
        doc_result = self._document_service().answer(goal, history=ctx.history, owner=ctx.owner)
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

    def _present_clarification(
        self,
        goal: str,
        classification,
        questions: list[str],
        ctx: TurnContext,
    ) -> dict[str, Any]:
        """Show guided options (or targeted questions) and remember the request."""
        # Per-owner pending-flow cap: don't let one principal pile up approvals.
        cap = quota_service.check_pending_flows(ctx.owner)
        if not cap:
            return self._limit_result(cap.message, cap.kind)
        pending = PendingClarification(
            original_request=goal,
            questions=questions,
            option_groups=option_groups_for(goal),
        )
        clarification_store.set(ctx.owner, pending)
        _ops_log("clarification_requested", ctx, original_request=goal)
        message = render_clarification_message(pending)
        ctx.trace.event(
            "clarification_options_presented",
            original_request=goal,
            option_count=len(pending.option_map),
        )

        result = self._clarification_result(classification)
        result["message"] = message
        result["final_answer"] = message
        result["meta"]["clarification_questions"] = questions
        result["meta"]["clarification_options"] = pending.option_map
        result["meta"]["awaiting_clarification"] = True
        # Machine-readable payload for interactive option cards (the readable
        # text above remains the fallback for older clients).
        structured = structured_clarification(pending)
        if structured is not None:
            result["meta"]["clarification"] = structured
        return result

    async def _resume_after_clarification(
        self,
        reply: str,
        pending: PendingClarification,
        selection: ClarificationSelection,
        ctx: TurnContext,
    ) -> dict[str, Any]:
        """Resolve the clarification into a concrete plan awaiting approval.

        A clarification answer is the missing information, not the final task:
        the supervisor reconstructs the original request with the exact
        selections, produces an execution plan, and gates execution behind
        approval. It must NOT report completion here — nothing ran yet — and it
        must never fall into the generic "needs a specific executable action"
        tool fallback.
        """
        # Atomic claim: a second resume (duplicate click / racing process) gets
        # None and is told honestly, so the original request is never re-run.
        if clarification_store.consume(ctx.owner) is None:
            return self._already_handled_result(
                "That clarification was already answered — send your next message to continue."
            )
        ctx.trace.event("clarification_received", reply=reply)
        ctx.trace.event(
            "clarification_resolved",
            original_request=pending.original_request,
            selected_options=selection.selected_options,
            custom_notes=selection.custom_notes,
        )
        ctx.trace.event(
            "workflow_resumed_after_clarification",
            original_request=pending.original_request,
            selected_options=selection.selected_options,
        )

        ctx.trace.event("stage", stage="planning")
        goal = build_continuation_goal(pending, selection)
        resolved_task = resolved_task_from(pending, selection)
        steps = generate_plan_steps(pending.original_request, selection)

        # Build the machine-readable plan now so approval can execute it with
        # real tools immediately (manifest design falls back deterministically
        # when no LLM is available).
        executable = build_executable_plan(
            pending.original_request,
            goal,
            resolved_task,
            generate=lambda **kwargs: LLMClient().generate(**kwargs),
        )

        plan = PendingPlan(
            original_request=pending.original_request,
            goal=goal,
            resolved_task=resolved_task,
            steps=steps,
            executable=executable.to_dict(),
        )
        plan_store.set(ctx.owner, plan)
        ctx.trace.event(
            "stage",
            stage="plan_ready",
            steps=len(steps),
            executable_steps=len(executable.steps),
        )

        message = render_plan_message(selection, steps)
        return {
            "run_id": uuid4().hex,
            "status": "plan_ready",
            "decision": "plan_ready",
            "mode": "execution_planning",
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
                "approval_required": True,
                "resumed_from_clarification": True,
                "resolved_task": resolved_task,
                "plan_steps": steps,
                "execution_plan": executable.to_dict(),
                "original_request": pending.original_request,
                "selected_options": selection.selected_options,
                **({"custom_notes": selection.custom_notes} if selection.custom_notes else {}),
            },
        }

    def _present_artifact_plan(
        self, goal: str, classification, kind: str, ctx: TurnContext
    ) -> dict[str, Any]:
        """Prepare artifact content + delivery, park a plan awaiting approval."""
        cap = quota_service.check_pending_flows(ctx.owner)
        if not cap:
            return self._limit_result(cap.message, cap.kind)
        ctx.trace.event("stage", stage="planning")
        context = None
        if ctx.has_uploaded_files:
            # Document-grounded artifacts: prepare from the uploaded files.
            try:
                doc = self._document_service().answer(goal, history=ctx.history, owner=ctx.owner)
                if doc.get("meta", {}).get("has_evidence"):
                    context = doc.get("message") or doc.get("final_answer")
            except Exception:
                context = None

        # No document grounding -> pull real substance from a bounded web-research
        # pass so the artifact carries facts, figures, and specifics rather than
        # thin stubs. Safe + optional: any failure falls back to ungrounded content.
        if context is None and settings.artifact_research_grounding:
            ctx.trace.event("stage", stage="collecting_sources")
            try:
                research = self.research.run(
                    goal,
                    history=ctx.history,
                    preferences=ctx.preferences,
                    want_web=True,
                    want_documents=False,
                    mode=WEB_RESEARCH_MODE,
                )
                grounded = (research.get("message") or research.get("final_answer") or "").strip()
                if len(grounded) > 80:
                    context = grounded
            except Exception:
                context = None

        # A saved artifact-style preference shapes generation as a default note.
        style_hint = preference_policy.artifact_style_hint(ctx.preferences)
        if style_hint:
            context = f"{style_hint}\n\n{context}" if context else style_hint

        from app.auth import owner_token_for

        pending, message = self.artifacts.plan(
            goal,
            kind,
            generate=lambda **kwargs: LLMClient().generate(**kwargs),
            context=context,
            owner_token=owner_token_for(ctx.owner),
            preferences=ctx.preferences,
        )
        artifact_store.set(ctx.owner, pending)
        ctx.trace.event("stage", stage="plan_ready", artifact_kind=kind)
        _ops_log("artifact_planned", ctx, kind=kind, status=pending.status)

        result = {
            "run_id": uuid4().hex,
            "status": "plan_ready",
            "decision": "artifact_plan_ready",
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
                "approval_required": True,
                "artifact_pending": True,
                "artifact_kind": kind,
                "plan_steps": ["Prepare content", "Generate file", "Validate it opens"],
                "save_location": pending.delivery.get("location"),
                "requested_path": pending.delivery.get("requested_path"),
            },
        }
        return self._with_classification(result, classification)

    async def _handle_artifact_reply(
        self, reply: str, pending: PendingArtifact, ctx: TurnContext
    ) -> dict[str, Any] | None:
        """Approve -> generate + validate the real file; reject -> honest stop."""
        decision = parse_plan_decision(reply)
        if decision is None:
            return None
        # Artifact-generation quota — checked before consuming so a blocked
        # approval leaves the artifact pending to retry later.
        if decision == "approve":
            quota = quota_service.check_windowed(ctx.owner, KIND_ARTIFACT)
            if not quota:
                return self._limit_result(quota.message, quota.kind)
        # Idempotent claim — a duplicate approval can't generate the file twice.
        if artifact_store.consume(ctx.owner) is None:
            return self._already_handled_result(
                "That artifact request was already handled — ask again to make a new one."
            )
        if decision == "approve":
            quota_service.record(ctx.owner, KIND_ARTIFACT)

        if decision == "reject":
            ctx.trace.event("artifact_rejected", kind=pending.kind)
            message = (
                f"Okay — I didn't generate the {pending.kind.upper()}. Tell me what "
                "to change and I'll prepare it again."
            )
            return self._artifact_response(
                "completed", "artifact_rejected", message, pending, ctx, artifact=None
            )

        ctx.trace.event("stage", stage="executing_workflow")
        _ops_log("artifact_generation_started", ctx, kind=pending.kind)
        outcome = self.artifacts.generate(pending)
        ctx.trace.event("stage", stage="validation")

        if outcome["status"] != "completed":
            ctx.trace.event("execution_completed", status="failed", kind=pending.kind)
            _ops_log("artifact_generation_finished", ctx, status="failed", kind=pending.kind)
            message = (
                f"I couldn't produce a valid {pending.kind.upper()} — {outcome.get('error', 'generation failed')}. "
                "The file was not created; tell me what to adjust and I'll retry."
            )
            return self._artifact_response(
                "failed", "artifact_generation_failed", message, pending, ctx, artifact=None,
                validation=outcome.get("validation"),
            )

        artifact = outcome["artifact"]
        ctx.trace.event(
            "execution_completed", status="completed", kind=pending.kind,
            validation=artifact.get("validation", {}).get("details"),
        )
        _ops_log("artifact_generation_finished", ctx, status="completed",
                 kind=pending.kind, filename=artifact["filename"])
        # Remember the last artifact so a follow-up revision ("add more detail /
        # images") can regenerate a richer version instead of falling into the
        # generic execution path. Ephemeral, session-scoped.
        session_memory.note(
            ctx.owner, ctx.session_id, "last_artifact",
            {"kind": pending.kind, "goal": pending.goal, "title": artifact.get("title", "")},
        )
        message = self._render_artifact_success(artifact)
        return self._artifact_response(
            "completed", "artifact_generated", message, pending, ctx,
            artifact=artifact, validation=artifact.get("validation"),
        )

    @staticmethod
    def _render_artifact_success(artifact: dict[str, Any]) -> str:
        details = artifact.get("validation", {}).get("details", {})
        kind = artifact["type"]
        if kind == "pptx":
            extent = f"{details.get('slides', '?')} slides"
        elif kind == "docx":
            extent = f"{details.get('paragraphs', '?')} paragraphs"
        else:
            extent = f"{details.get('rows', '?')} rows"
        note = ""
        if artifact.get("location") == "external" and artifact.get("requested_path"):
            note = (
                f" You asked to save it to {artifact['requested_path']}; for safety "
                "it's in the workspace download area."
            )
        # The clickable artifact card carries the download — keep the prose clean
        # (no raw URL). The download_url stays in the artifact metadata.
        return (
            f"Created “{artifact['title']}” ({kind.upper()}, {extent}) and validated "
            f"it opens correctly.{note} Your download is ready below."
        )

    def _artifact_response(
        self, status, decision, message, pending: PendingArtifact, ctx: TurnContext,
        *, artifact: dict[str, Any] | None, validation: dict | None = None,
    ) -> dict[str, Any]:
        artifacts = [artifact] if artifact else []
        return {
            "run_id": uuid4().hex,
            "status": status,
            "decision": decision,
            "mode": "research_then_execution",
            "message": message,
            "final_answer": message,
            "sources": [],
            "artifacts": artifacts,
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": False,
                "has_artifacts": bool(artifacts),
                "requires_approval": False,
                "artifact_kind": pending.kind,
                **({"artifact": artifact} if artifact else {}),
                **({"validation": validation} if validation else {}),
                "original_request": pending.goal,
            },
        }

    async def _handle_action_reply(
        self, reply: str, pending: PendingAction, ctx: TurnContext
    ) -> dict[str, Any] | None:
        """Approve/reject gated runtime actions; None routes the turn normally."""
        decision = parse_plan_decision(reply)
        if decision is None:
            return None
        # Startup/runtime-validation quota — checked before consuming so a
        # blocked approval leaves the actions pending to retry later.
        if decision == "approve":
            quota = quota_service.check_windowed(ctx.owner, KIND_STARTUP)
            if not quota:
                return self._limit_result(quota.message, quota.kind)
        # Idempotent claim — duplicate approvals can't re-run validation.
        if action_store.consume(ctx.owner) is None:
            return self._already_handled_result(
                "Those validation steps were already handled — send a new request to continue."
            )
        if decision == "approve":
            quota_service.record(ctx.owner, KIND_STARTUP)

        if decision == "reject":
            ctx.trace.event("runtime_validation_rejected")
            message = (
                "Okay — skipping runtime validation. The generated files are "
                f"kept under {pending.project_dir}/ and remain syntax-validated."
            )
            status, evidence = "completed", {}
        else:
            ctx.trace.event("action_approved", actions=len(pending.actions))
            ctx.trace.event("stage", stage="executing_workflow")
            _ops_log("runtime_validation_started", ctx, actions=len(pending.actions))
            executable = ExecutablePlan.from_dict(pending.plan)
            evidence = execute_runtime_validation(
                executable,
                pending.actions,
                generate=lambda **kwargs: LLMClient().generate(**kwargs),
                on_event=lambda event, data: ctx.trace.event("stage", stage=event, **data),
            )
            ctx.trace.event("stage", stage="validation")
            message = render_runtime_report(evidence)
            status = "completed" if evidence.get("status") == "completed" else "failed"
            ctx.trace.event("execution_completed", status=status)
            _ops_log("runtime_validation_finished", ctx, status=status,
                     failure_class=evidence.get("failure_class"),
                     repairs=len(evidence.get("repairs", [])))

        return {
            "run_id": uuid4().hex,
            "status": status,
            "decision": "runtime_validated" if status == "completed" else "runtime_validation_failed",
            "mode": "execution_planning",
            "message": message,
            "final_answer": message,
            "sources": [],
            "artifacts": list(pending.files),
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": False,
                "has_artifacts": bool(pending.files),
                "requires_approval": False,
                "runtime": evidence,
                "files_written": [{"path": p} for p in pending.files],
                "original_request": pending.goal,
            },
        }

    async def _handle_plan_reply(
        self, reply: str, plan: PendingPlan, ctx: TurnContext
    ) -> dict[str, Any] | None:
        """Approve/reject a pending plan; None routes the turn normally."""
        decision = parse_plan_decision(reply)
        if decision is None:
            return None
        # Execution-start quota — checked BEFORE consuming so a blocked approval
        # leaves the plan pending to retry once the window clears.
        if decision == "approve":
            quota = quota_service.check_windowed(ctx.owner, KIND_EXECUTION)
            if not quota:
                return self._limit_result(quota.message, quota.kind)
        # Idempotent claim: only the first approve/reject runs; a duplicate (or
        # a racing process) gets None and is told honestly — never double-runs.
        claimed = plan_store.consume(ctx.owner)
        if claimed is None:
            return self._already_handled_result(
                "That plan was already approved or discarded — send a new request to continue."
            )
        plan = claimed
        if decision == "approve":
            quota_service.record(ctx.owner, KIND_EXECUTION)
            return await self._execute_approved_plan(plan, ctx)
        if decision == "reject":
            ctx.trace.event("plan_discarded", original_request=plan.original_request)
            message = (
                "Okay — I've discarded that plan. Tell me what you'd like to "
                "change, or describe the task again."
            )
            return {
                "run_id": uuid4().hex,
                "status": "completed",
                "decision": "plan_discarded",
                "mode": "execution_planning",
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
                    "original_request": plan.original_request,
                },
            }
        return None

    async def _execute_approved_plan(
        self, plan: PendingPlan, ctx: TurnContext
    ) -> dict[str, Any]:
        """Execute the approved plan with REAL tools, step by step.

        prepare -> safety check -> tool call -> validate -> repair/retry ->
        continue. Completion is only reported with evidence: files written to
        disk, read back, and validated. Prose is never accepted as execution.

        The plan was already atomically claimed in `_handle_plan_reply`, so this
        runs exactly once.
        """
        ctx.trace.event("plan_approved", original_request=plan.original_request)
        ctx.trace.event("stage", stage="executing_workflow")
        _ops_log("execution_started", ctx, original_request=plan.original_request)

        if plan.executable:
            executable = ExecutablePlan.from_dict(plan.executable)
        else:
            executable = build_executable_plan(
                plan.original_request,
                plan.goal,
                plan.resolved_task,
                generate=lambda **kwargs: LLMClient().generate(**kwargs),
            )

        def _on_event(event: str, data: dict[str, Any]) -> None:
            ctx.trace.event("stage", stage=event, **data)

        report = execute_plan(
            executable,
            generate=lambda **kwargs: LLMClient().generate(**kwargs),
            on_event=_on_event,
        )

        ctx.trace.event("stage", stage="validation")
        message = render_execution_report(executable, report)

        # Self-check: offer gated runtime validation (install + run) for the
        # generated project. Risky commands need their own approval.
        runtime_actions: list[dict[str, Any]] = []
        if report.status == "completed":
            runtime_actions = build_runtime_actions(executable, report)

        if report.status == "completed" and runtime_actions:
            action_store.set(
                ctx.session_id,
                PendingAction(
                    goal=plan.goal,
                    project_dir=executable.project_dir,
                    plan=executable.to_dict(),
                    actions=runtime_actions,
                    files=[entry["path"] for entry in report.files_written],
                ),
            )
            status, decision = "awaiting_action_approval", "plan_executed"
            message += "\n" + render_runtime_offer(runtime_actions)
            ctx.trace.event("stage", stage="awaiting_action_approval")
        elif report.status == "completed":
            status, decision = "completed", "plan_executed"
        else:
            status, decision = "failed", "plan_execution_failed"

        ctx.trace.event(
            "execution_completed",
            status=status,
            files_written=len(report.files_written),
            repairs=len(report.repairs),
        )
        _ops_log("execution_finished", ctx, status=status,
                 files_written=len(report.files_written), repairs=len(report.repairs))
        return {
            "run_id": uuid4().hex,
            "status": status,
            "decision": decision,
            "mode": "execution_planning",
            "message": message,
            "final_answer": message,
            "sources": [],
            "artifacts": [entry["path"] for entry in report.files_written],
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": False,
                "has_artifacts": bool(report.files_written),
                "requires_approval": False,
                "approval_required": bool(runtime_actions),
                **(
                    {"plan_steps": [a["description"] for a in runtime_actions]}
                    if runtime_actions
                    else {}
                ),
                "executed_plan_steps": plan.steps,
                "execution_plan": executable.to_dict(),
                "files_written": report.files_written,
                "validation": report.validation,
                "repairs": report.repairs,
                "runtime_actions": runtime_actions,
                "resolved_task": plan.resolved_task,
                "original_request": plan.original_request,
            },
        }

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
            _ops_log("turn_completed", ctx, run_id=response.run_id,
                     mode=response.mode, status=response.status,
                     latency_ms=ctx.trace.elapsed_ms())
        except Exception:
            pass

    async def _dispatch(self, goal: str, ctx: TurnContext) -> dict[str, Any]:
        # An artifact plan awaiting approval: approve -> generate, reject -> stop.
        pending_artifact = artifact_store.get(ctx.owner)
        if pending_artifact is not None:
            handled = await self._handle_artifact_reply(goal, pending_artifact, ctx)
            if handled is not None:
                return handled

        # Runtime actions awaiting per-action approval: approve -> run + verify.
        pending_action = action_store.get(ctx.owner)
        if pending_action is not None:
            handled = await self._handle_action_reply(goal, pending_action, ctx)
            if handled is not None:
                return handled

        # A plan awaiting approval: approve -> execute, reject -> discard.
        plan = plan_store.get(ctx.owner)
        if plan is not None:
            handled = await self._handle_plan_reply(goal, plan, ctx)
            if handled is not None:
                return handled

        # A pending clarification for this session: if this message answers it,
        # resume the original task with the selected choices.
        pending = clarification_store.get(ctx.owner)
        if pending is not None:
            selection = parse_selection(goal, pending)
            if selection is not None:
                return await self._resume_after_clarification(goal, pending, selection, ctx)

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
        _ops_log("route_chosen", ctx, mode=classification.mode,
                 confidence=classification.confidence,
                 conversation_type=reasoning.conversation_type)

        if classification.mode in CONVERSATIONAL_MODES:
            # Direct-answer path: conversational/knowledge/self-memory turns
            # answer through the dedicated service, never the workflow.
            message = self.answers.answer(
                goal,
                mode=classification.mode,
                history=ctx.history,
                preferences=ctx.preferences,
            )
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

    def _limit_result(self, message: str, kind: str) -> dict[str, Any]:
        """Honest, clean response when a usage quota is hit (state untouched).

        Detailed classification lives in meta/logs, not the user-facing text.
        """
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "rate_limited",
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
                "rate_limited": True,
                "limit_kind": kind,
            },
        }

    def _already_handled_result(self, message: str) -> dict[str, Any]:
        """Honest response when a guided step was already consumed or expired.

        Returned when an atomic claim fails (duplicate click, racing process,
        restart after completion, or a stale/expired flow) — never a fabricated
        re-run of the original work.
        """
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": "already_handled",
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
                "already_handled": True,
            },
        }

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
