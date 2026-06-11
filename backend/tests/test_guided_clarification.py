# File: backend/tests/test_guided_clarification.py
"""Guided clarification options with real continuation (Phase 2A enhancement)."""

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.clarification import (
    PendingClarification,
    build_continuation_goal,
    clarification_store,
    option_groups_for,
    parse_selection,
    render_clarification_message,
)
from app.context_builder import build_turn_context
from app.supervisor_reasoning import reason_about_turn

_SESSION = "clarify-test-session"
_RAG_GOAL = "Build me a RAG system"


@pytest.fixture(autouse=True)
def _clean_store():
    clarification_store.clear(_SESSION)
    clarification_store.clear(None)
    yield
    clarification_store.clear(_SESSION)
    clarification_store.clear(None)


def _rag_pending() -> PendingClarification:
    return PendingClarification(
        original_request=_RAG_GOAL,
        questions=["What should it be built with (stack, tools, or format)?"],
        option_groups=option_groups_for(_RAG_GOAL),
    )


async def _present_rag_clarification(supervisor: AssistantSupervisor):
    ctx = build_turn_context(_RAG_GOAL, session_id=_SESSION, run_id="t-present")
    reasoning = reason_about_turn(_RAG_GOAL)
    result = await supervisor._dispatch_non_chat(
        _RAG_GOAL, reasoning.classification, ctx, reasoning=reasoning
    )
    return result, ctx


class _ExecutionCapture:
    """Stands in for ExecutionService and records the dispatched goal."""

    def __init__(self):
        self.goals: list[str] = []

    async def run(self, goal, mode=None, **kwargs):
        self.goals.append(goal)
        return {
            "run_id": "exec-run",
            "status": "completed",
            "decision": "execution_completed",
            "mode": "execution",
            "message": "Workflow executed.",
            "final_answer": "Workflow executed.",
            "sources": [],
            "artifacts": [],
            "approval_summary": None,
            "meta": {},
        }


# ── 1-4: structured options ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rag_request_returns_structured_options():
    supervisor = AssistantSupervisor()
    result, ctx = await _present_rag_clarification(supervisor)

    assert result["mode"] == "clarification"
    assert result["meta"]["awaiting_clarification"] is True
    message = result["message"]
    assert "1. Stack" in message
    assert "2. Tools" in message
    assert "3. Output format" in message
    assert "Reply like: 1B, 2B, 3B" in message
    # Pending state was remembered for the session.
    pending = clarification_store.get(_SESSION)
    assert pending is not None
    assert pending.original_request == _RAG_GOAL
    assert pending.status == "awaiting_clarification"


def test_stack_options_match_spec():
    groups = option_groups_for(_RAG_GOAL)
    assert groups[1]["A"] == "FastAPI + ChromaDB + Groq"
    assert groups[1]["B"] == "Next.js + FastAPI + FAISS"
    assert groups[1]["C"] == "LangChain + ChromaDB + OpenAI-compatible LLM"
    assert groups[1]["D"] == "Custom stack"


def test_tool_options_match_spec():
    groups = option_groups_for(_RAG_GOAL)
    assert groups[2]["A"] == "PDF upload + semantic search"
    assert groups[2]["B"] == "Hybrid search + citations"
    assert groups[2]["C"] == "Multi-document Q&A + memory"
    assert groups[2]["D"] == "Custom tools"


def test_output_format_options_match_spec():
    groups = option_groups_for(_RAG_GOAL)
    assert groups[3]["A"] == "Step-by-step implementation plan"
    assert groups[3]["B"] == "Backend implementation"
    assert groups[3]["C"] == "Full backend + frontend structure"
    assert groups[3]["D"] == "Custom format"


# ── 5-7: code selection resumes with the chosen technologies ─────────────────


@pytest.mark.asyncio
async def test_code_reply_resumes_original_request_with_choices():
    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecutionCapture()
    await _present_rag_clarification(supervisor)

    ctx = build_turn_context("1B, 2B, 3B", session_id=_SESSION, run_id="t-resume")
    result = await supervisor._dispatch("1B, 2B, 3B", ctx)

    # Resumed — not another clarification.
    assert result["mode"] != "clarification"
    assert result["meta"]["resumed_from_clarification"] is True
    assert result["meta"]["original_request"] == _RAG_GOAL
    assert result["meta"]["selected_options"] == {
        "Stack": "Next.js + FastAPI + FAISS",
        "Tools": "Hybrid search + citations",
        "Output format": "Backend implementation",
    }

    # The dispatched goal carries the original request AND the exact choices.
    dispatched = supervisor.execution.goals[0]
    assert _RAG_GOAL in dispatched
    assert "Next.js + FastAPI + FAISS" in dispatched
    assert "Hybrid search + citations" in dispatched
    assert "Backend implementation" in dispatched

    # The acknowledgment confirms the selection in the reply.
    assert "Next.js + FastAPI + FAISS" in result["message"]

    # Pending state is resolved — the same reply would not be re-interpreted.
    assert clarification_store.get(_SESSION) is None


def test_selected_faiss_stack_excludes_chromadb():
    pending = _rag_pending()
    selection = parse_selection("1B, 2B, 3B", pending)
    goal = build_continuation_goal(pending, selection)

    assert "FAISS" in goal
    assert "ChromaDB" not in goal
    assert "Do not ask for clarification again" in goal
    assert "do not substitute different technologies" in goal


def test_free_text_stack_selection_parses():
    pending = _rag_pending()
    selection = parse_selection(
        "Use Next.js + FastAPI + FAISS and generate the backend", pending
    )
    assert selection is not None
    assert selection.choices[1] == "Next.js + FastAPI + FAISS"
    assert selection.choices[3] == "Backend implementation"


def test_ordinal_selection_parses():
    pending = _rag_pending()
    selection = parse_selection("use the second stack", pending)
    assert selection is not None
    assert selection.choices[1] == "Next.js + FastAPI + FAISS"


# ── 8: custom answers ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_answer_resumes_with_custom_notes():
    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecutionCapture()
    await _present_rag_clarification(supervisor)

    reply = "Custom: use FastAPI, Qdrant, and Claude"
    ctx = build_turn_context(reply, session_id=_SESSION, run_id="t-custom")
    result = await supervisor._dispatch(reply, ctx)

    assert result["meta"]["resumed_from_clarification"] is True
    dispatched = supervisor.execution.goals[0]
    assert _RAG_GOAL in dispatched
    assert "Qdrant" in dispatched
    assert clarification_store.get(_SESSION) is None


# ── 9: awaiting state, not success ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_clarification_is_awaiting_not_completed_task():
    supervisor = AssistantSupervisor()
    result, _ = await _present_rag_clarification(supervisor)

    # The UI keys off mode=clarification + awaiting flag — it must be clearly
    # distinguishable from a completed task.
    assert result["mode"] == "clarification"
    assert result["decision"] == "clarification"
    assert result["meta"]["awaiting_clarification"] is True


# ── 10: tracing ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_includes_clarification_events():
    supervisor = AssistantSupervisor()
    supervisor.execution = _ExecutionCapture()
    _, present_ctx = await _present_rag_clarification(supervisor)

    present_names = [e["name"] for e in present_ctx.trace.events]
    assert "clarification_requested" in present_names
    assert "clarification_options_presented" in present_names

    resume_ctx = build_turn_context("1A, 2A, 3A", session_id=_SESSION, run_id="t-trace")
    await supervisor._dispatch("1A, 2A, 3A", resume_ctx)

    resume_names = [e["name"] for e in resume_ctx.trace.events]
    assert "clarification_received" in resume_names
    assert "clarification_resolved" in resume_names
    assert "workflow_resumed_after_clarification" in resume_names

    resolved = next(e for e in resume_ctx.trace.events if e["name"] == "clarification_resolved")
    assert resolved["original_request"] == _RAG_GOAL
    assert resolved["selected_options"]["Stack"] == "FastAPI + ChromaDB + Groq"


# ── 11: clear requests + unrelated turns stay safe ───────────────────────────


@pytest.mark.parametrize(
    "clear_request",
    ["git push", "install package requests", "make a ppt about transformers"],
)
def test_clear_requests_still_skip_clarification(clear_request):
    reasoning = reason_about_turn(clear_request)
    assert reasoning.needs_clarification is False


def test_unrelated_question_does_not_resolve_pending():
    pending = _rag_pending()
    assert parse_selection("what is FAISS?", pending) is None
    assert parse_selection("how does hybrid search work", pending) is None


def test_unrelated_command_does_not_resolve_pending():
    pending = _rag_pending()
    assert parse_selection("git push", pending) is None


def test_non_rag_clarification_uses_plain_questions():
    pending = PendingClarification(
        original_request="Deploy my application",
        questions=["Which application or project should I work with?"],
        option_groups=option_groups_for("Deploy my application"),
    )
    assert pending.option_groups == {}
    message = render_clarification_message(pending)
    assert "Which application" in message
    assert "Reply like" not in message
