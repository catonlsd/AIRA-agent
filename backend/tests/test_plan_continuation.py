# File: backend/tests/test_plan_continuation.py
"""Clarification selection must resume real planning/execution — not claim
completion, and never hit the generic "needs a specific executable action"
tool fallback."""

import pytest

import app.assistant_supervisor as sup_module
from app.assistant_supervisor import AssistantSupervisor
from app.clarification import (
    ClarificationSelection,
    action_store,
    clarification_store,
    generate_plan_steps,
    parse_plan_decision,
    plan_store,
)
from app.context_builder import build_turn_context
from app.supervisor_reasoning import reason_about_turn

_SESSION = "plan-test-session"
_RAG_GOAL = "Build me a RAG system"
_FALLBACK = "needs a specific executable action"


@pytest.fixture(autouse=True)
def _clean_stores():
    for store in (clarification_store, plan_store, action_store):
        store.clear(_SESSION)
        store.clear(None)
    yield
    for store in (clarification_store, plan_store, action_store):
        store.clear(_SESSION)
        store.clear(None)


async def _resolve_rag(
    supervisor: AssistantSupervisor,
    stack: str = "Next.js + FastAPI + FAISS",
    tools: str = "Hybrid search + citations",
    output_format: str = "Backend implementation",
):
    """Present the RAG clarification, then answer it with the given choices."""
    present_ctx = build_turn_context(_RAG_GOAL, session_id=_SESSION, run_id="p-present")
    reasoning = reason_about_turn(_RAG_GOAL)
    await supervisor._dispatch_non_chat(
        _RAG_GOAL, reasoning.classification, present_ctx, reasoning=reasoning
    )

    reply = (
        "Clarification response:\n"
        f"Original request: {_RAG_GOAL}\n"
        f"Stack: {stack}\n"
        f"Tools: {tools}\n"
        f"Output format: {output_format}"
    )
    resume_ctx = build_turn_context(reply, session_id=_SESSION, run_id="p-resume")
    result = await supervisor._dispatch(reply, resume_ctx)
    return result, resume_ctx


# ── 1. No "Execution complete" after selection ───────────────────────────────


@pytest.mark.asyncio
async def test_selection_does_not_return_execution_complete():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)

    assert result["status"] == "plan_ready"
    assert result["decision"] != "execution_completed"
    assert "execution complete" not in result["message"].lower()


# ── 2. Resolved task record ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_selection_creates_resolved_task():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)

    resolved = result["meta"]["resolved_task"]
    assert resolved["original_request"] == _RAG_GOAL
    assert resolved["selected_stack"] == "Next.js + FastAPI + FAISS"
    assert resolved["selected_tools"] == "Hybrid search + citations"
    assert resolved["selected_output_format"] == "Backend implementation"
    assert resolved["custom_notes"] is None


# ── 3-4. Plan exists and preserves the stack ─────────────────────────────────


@pytest.mark.asyncio
async def test_rag_selection_creates_execution_plan():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)

    steps = result["meta"]["plan_steps"]
    assert len(steps) >= 4
    assert any("inspect" in step.lower() for step in steps)
    assert any("valid" in step.lower() for step in steps)
    # The numbered plan appears in the reply too.
    assert "Plan:" in result["message"]
    assert "1." in result["message"]


@pytest.mark.asyncio
async def test_selected_stack_is_preserved_in_plan():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)

    steps = " ".join(result["meta"]["plan_steps"])
    assert "Next.js + FastAPI + FAISS" in steps


# ── 5-6. Vector store fidelity ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faiss_selection_produces_faiss_plan_not_chromadb():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor, stack="Next.js + FastAPI + FAISS")

    plan_text = " ".join(result["meta"]["plan_steps"]) + result["message"]
    assert "FAISS" in plan_text
    assert "ChromaDB" not in plan_text


@pytest.mark.asyncio
async def test_chromadb_selection_produces_chromadb_plan():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor, stack="FastAPI + ChromaDB + Groq")

    plan_text = " ".join(result["meta"]["plan_steps"])
    assert "ChromaDB" in plan_text
    assert "FAISS" not in plan_text


# ── 7-8. Output-format awareness ─────────────────────────────────────────────


def test_backend_only_output_has_no_frontend_steps():
    selection = ClarificationSelection(
        choices={1: "FastAPI + ChromaDB + Groq", 2: "PDF upload + semantic search", 3: "Backend implementation"}
    )
    steps = generate_plan_steps(_RAG_GOAL, selection)
    assert not any("frontend" in step.lower() for step in steps)
    assert any("backend" in step.lower() for step in steps)


def test_full_stack_output_has_backend_and_frontend_steps():
    selection = ClarificationSelection(
        choices={1: "FastAPI + ChromaDB + Groq", 2: "Multi-document Q&A + memory", 3: "Full backend + frontend structure"}
    )
    steps = generate_plan_steps(_RAG_GOAL, selection)
    assert any("backend" in step.lower() for step in steps)
    assert any("frontend" in step.lower() for step in steps)


# ── 9. Approval gate before file changes ─────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_requires_approval_before_file_changes():
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)

    assert result["meta"]["approval_required"] is True
    assert "Approval required before modifying project files" in result["message"]
    # The plan is parked, waiting for the user's go-ahead.
    plan = plan_store.get(_SESSION)
    assert plan is not None
    assert plan.status == "awaiting_plan_approval"
    # The machine-readable plan is already prepared for execution.
    assert plan.executable is not None
    assert plan.executable["steps"]


# ── 10. No generic tool fallback after a valid selection ─────────────────────


def _sandbox_workspace(monkeypatch, tmp_path):
    """Point the file tool's sandboxed workspace at a temp directory."""
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))


def _stub_codegen(monkeypatch, captured=None):
    """LLM stub: a small JSON manifest for planning, valid code for files."""

    def _fake_generate(self, system, prompt, temperature=0.2):
        if captured is not None:
            captured["system"] = system
            captured["prompt"] = prompt
        if "JSON array" in system or "JSON array" in prompt:
            return (
                '[{"path": "app/main.py", "purpose": "FastAPI entrypoint"},'
                ' {"path": "README.md", "purpose": "Setup instructions"}]'
            )
        return "# FastAPI + FAISS implementation\nprint('service ready')\n"

    monkeypatch.setattr(sup_module.LLMClient, "generate", _fake_generate)


@pytest.mark.asyncio
async def test_no_executable_action_fallback_after_selection(monkeypatch, tmp_path):
    _sandbox_workspace(monkeypatch, tmp_path)
    supervisor = AssistantSupervisor()
    result, _ = await _resolve_rag(supervisor)
    assert _FALLBACK not in result["message"]

    # Even after approval, the supervisor executes the plan directly and never
    # routes into the keyword tool planner's fallback.
    _stub_codegen(monkeypatch)
    approve_ctx = build_turn_context("approve plan", session_id=_SESSION, run_id="p-approve")
    executed = await supervisor._dispatch("approve plan", approve_ctx)
    assert _FALLBACK not in executed["message"]


# ── 11. Completed only after actual execution (with real evidence) ──────────


@pytest.mark.asyncio
async def test_completed_only_after_actual_execution(monkeypatch, tmp_path):
    """Full state machine: plan_ready -> executing -> awaiting_action_approval
    -> runtime validation -> completed, with real evidence at each gate."""
    _sandbox_workspace(monkeypatch, tmp_path)
    supervisor = AssistantSupervisor()
    captured = {}
    _stub_codegen(monkeypatch, captured)

    result, _ = await _resolve_rag(supervisor)
    assert result["status"] == "plan_ready"  # not completed yet
    # The machine-readable plan rides along for the UI.
    assert result["meta"]["execution_plan"]["steps"]

    approve_ctx = build_turn_context("approve plan", session_id=_SESSION, run_id="p-exec")
    executed = await supervisor._dispatch("approve plan", approve_ctx)

    # Files written + validated, but the run now offers gated runtime
    # validation (the project contains .py files) — still not "completed".
    assert executed["status"] == "awaiting_action_approval"
    assert executed["decision"] == "plan_executed"
    files = executed["meta"]["files_written"]
    assert files, "execution requires written files"
    for entry in files:
        assert (tmp_path / entry["path"]).exists()
        assert entry["path"] in executed["message"]
    assert executed["meta"]["validation"]["missing_or_invalid"] == []
    assert executed["meta"]["runtime_actions"]
    assert "never" in captured["system"].lower()
    assert _RAG_GOAL in captured["prompt"]
    assert plan_store.get(_SESSION) is None
    assert action_store.get(_SESSION) is not None
    stages = [e.get("stage") for e in approve_ctx.trace.events if e.get("name") == "stage"]
    assert "executing_workflow" in stages
    assert "executing_step" in stages
    assert "validating" in stages
    assert "awaiting_action_approval" in stages

    # Approve the runtime actions: commands actually run (stubbed runner) and
    # only then does the run report completed — with command evidence.
    from tools.tool_router import ToolRouter

    commands_run = []

    def _fake_run(tool_name, action, payload=None):
        commands_run.append((tool_name, action, (payload or {}).get("command", "")))
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(ToolRouter, "run", staticmethod(_fake_run))

    run_ctx = build_turn_context("approve", session_id=_SESSION, run_id="p-runtime")
    validated = await supervisor._dispatch("approve", run_ctx)

    assert validated["status"] == "completed"
    assert validated["decision"] == "runtime_validated"
    runtime = validated["meta"]["runtime"]
    assert runtime["status"] == "completed"
    assert any("compileall" in cmd for _, _, cmd in commands_run)
    assert all(entry["success"] for entry in runtime["commands"])
    assert action_store.get(_SESSION) is None


@pytest.mark.asyncio
async def test_rejecting_runtime_validation_keeps_files(monkeypatch, tmp_path):
    _sandbox_workspace(monkeypatch, tmp_path)
    supervisor = AssistantSupervisor()
    _stub_codegen(monkeypatch)
    await _resolve_rag(supervisor)

    approve_ctx = build_turn_context("approve plan", session_id=_SESSION, run_id="p-x1")
    executed = await supervisor._dispatch("approve plan", approve_ctx)
    assert executed["status"] == "awaiting_action_approval"

    reject_ctx = build_turn_context("reject", session_id=_SESSION, run_id="p-x2")
    result = await supervisor._dispatch("reject", reject_ctx)

    assert result["status"] == "completed"
    assert "skipping runtime validation" in result["message"].lower()
    assert action_store.get(_SESSION) is None
    # The generated files survive.
    for entry in executed["meta"]["files_written"]:
        assert (tmp_path / entry["path"]).exists()


# ── Plan decision parsing + rejection ────────────────────────────────────────


def test_plan_decision_parsing():
    assert parse_plan_decision("approve plan") == "approve"
    assert parse_plan_decision("Approve") == "approve"
    assert parse_plan_decision("yes, go ahead") == "approve"
    assert parse_plan_decision("looks good") == "approve"
    assert parse_plan_decision("reject") == "reject"
    assert parse_plan_decision("cancel") == "reject"
    # Unrelated messages route normally.
    assert parse_plan_decision("what is FAISS?") is None
    assert parse_plan_decision("git push") is None


@pytest.mark.asyncio
async def test_rejecting_plan_discards_it():
    supervisor = AssistantSupervisor()
    await _resolve_rag(supervisor)

    reject_ctx = build_turn_context("cancel", session_id=_SESSION, run_id="p-reject")
    result = await supervisor._dispatch("cancel", reject_ctx)

    assert result["decision"] == "plan_discarded"
    assert plan_store.get(_SESSION) is None
