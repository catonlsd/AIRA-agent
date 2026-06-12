# File: backend/tests/test_regression_wall.py
"""Regression wall around the control plane and execution semantics.

Protects: routed top-level modes, the execution state machine
(plan_ready -> executing -> validating -> awaiting_action_approval ->
completed/failed), approval/resume, evidence-gated completion, runtime
validation ordering, and the SSE lifecycle for guided execution flows.
"""

import pytest

import app.assistant_supervisor as sup_module
from app.assistant_supervisor import AssistantSupervisor
from app.clarification import action_store, clarification_store, plan_store
from app.context_builder import build_turn_context
from app.plan_executor import (
    ExecutablePlan,
    ExecutionReport,
    PlanStep,
    build_runtime_actions,
    execute_runtime_validation,
)

_SESSION = "regression-wall-session"
_RAG_GOAL = "Build me a RAG system"
_STRUCTURED_REPLY = (
    "Clarification response:\n"
    f"Original request: {_RAG_GOAL}\n"
    "Stack: Next.js + FastAPI + FAISS\n"
    "Tools: Hybrid search + citations\n"
    "Output format: Backend implementation"
)


@pytest.fixture(autouse=True)
def _clean_stores():
    for store in (clarification_store, plan_store, action_store):
        store.clear(_SESSION)
        store.clear(None)
    yield
    for store in (clarification_store, plan_store, action_store):
        store.clear(_SESSION)
        store.clear(None)


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    from tools.filesystem.file_tool import FileTool

    monkeypatch.setattr(FileTool, "_workspace_root", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def codegen_stub(monkeypatch):
    def _fake_generate(self, system, prompt, temperature=0.2):
        if "JSON array" in system or "JSON array" in prompt:
            return (
                '[{"path": "app/main.py", "purpose": "FastAPI entrypoint"},'
                ' {"path": "README.md", "purpose": "Setup instructions"}]'
            )
        return "# FastAPI + FAISS implementation\nprint('service ready')\n"

    monkeypatch.setattr(sup_module.LLMClient, "generate", _fake_generate)


async def _stream(supervisor: AssistantSupervisor, message: str, run_id: str):
    ctx = build_turn_context(message, session_id=_SESSION, run_id=run_id)
    return [event async for event in supervisor.stream_turn(ctx)]


def _final(events):
    finals = [e for e in events if e["type"] == "final"]
    assert len(finals) == 1, "exactly one final event per stream"
    return finals[0]["data"]


# ── SSE lifecycle: the full guided execution state machine over the stream ───


@pytest.mark.asyncio
async def test_sse_guided_execution_lifecycle(monkeypatch, sandbox, codegen_stub):
    supervisor = AssistantSupervisor()

    # 1. Vague execution request -> streamed clarification (never completed-work).
    events = await _stream(supervisor, _RAG_GOAL, "rw-1")
    assert events[0]["type"] == "trace"  # trace events lead every stream
    final1 = _final(events)
    assert final1["mode"] == "clarification"
    assert final1.get("meta", {}).get("awaiting_clarification") is True
    # The stream announced the clarifying stage before answering.
    stages = [e["data"].get("stage") for e in events if e["type"] == "trace"]
    assert "clarifying" in stages

    # 2. Structured answer -> plan_ready (a plan is NOT completion).
    final2 = _final(await _stream(supervisor, _STRUCTURED_REPLY, "rw-2"))
    assert final2["status"] == "plan_ready"
    assert final2["decision"] == "plan_ready"
    assert final2["mode"] != "single_question"
    meta2 = final2.get("meta", {})
    assert meta2.get("approval_required") is True
    assert meta2.get("execution_plan", {}).get("steps")
    assert "files_written" not in meta2  # no fabricated evidence at plan time

    # 3. Approve plan -> real execution -> files on disk -> awaiting_action_approval.
    final3 = _final(await _stream(supervisor, "approve plan", "rw-3"))
    assert final3["status"] == "awaiting_action_approval"
    assert final3["decision"] == "plan_executed"
    meta3 = final3.get("meta", {})
    files = meta3.get("files_written", [])
    assert files, "execution must produce file evidence"
    for entry in files:
        assert (sandbox / entry["path"]).exists()
    assert meta3.get("validation", {}).get("missing_or_invalid") == []
    assert meta3.get("runtime_actions")

    # 4. Approve runtime actions -> commands run -> ONLY NOW completed.
    from tools.tool_router import ToolRouter

    ran = []

    def _fake_run(tool_name, action, payload=None):
        ran.append((payload or {}).get("command", f"{tool_name}.{action}"))
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(ToolRouter, "run", staticmethod(_fake_run))

    final4 = _final(await _stream(supervisor, "approve", "rw-4"))
    assert final4["status"] == "completed"
    assert final4["decision"] == "runtime_validated"
    runtime = final4.get("meta", {}).get("runtime", {})
    assert runtime.get("status") == "completed"
    assert runtime.get("commands"), "runtime evidence must record commands"
    assert any("compileall" in cmd for cmd in ran)

    # The observed status progression is the legal state machine, in order.
    progression = [final1.get("status"), final2["status"], final3["status"], final4["status"]]
    assert progression[1:] == ["plan_ready", "awaiting_action_approval", "completed"]
    # No stream ever claimed completion before evidence existed.
    assert "completed" not in progression[:3] or progression.index("completed") == 0


@pytest.mark.asyncio
async def test_sse_event_ordering_is_stable(sandbox, codegen_stub):
    supervisor = AssistantSupervisor()
    events = await _stream(supervisor, _RAG_GOAL, "rw-order")
    types = [e["type"] for e in events]
    # trace events first, final last, tokens (if any) strictly before final.
    assert types[0] == "trace"
    assert types[-1] == "final"
    if "token" in types:
        assert types.index("token") < types.index("final")


# ── Approval/resume safety + idempotency ─────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_without_pending_state_routes_normally(monkeypatch):
    """A bare "approve" with nothing pending must not fabricate a resume."""
    supervisor = AssistantSupervisor()

    class _ExecStub:
        async def run(self, goal, mode=None, **kwargs):
            return {
                "run_id": "x",
                "status": "completed",
                "decision": "execution_completed",
                "mode": "execution",
                "message": "ran",
                "final_answer": "ran",
                "sources": [],
                "artifacts": [],
                "approval_summary": None,
                "meta": {},
            }

    supervisor.execution = _ExecStub()
    monkeypatch.setattr(
        sup_module, "generate_conversational_answer", lambda goal, history=None: "ok"
    )

    ctx = build_turn_context("approve", session_id=_SESSION, run_id="rw-idem")
    result = await supervisor._dispatch("approve", ctx)

    assert result["decision"] not in (
        "runtime_validated",
        "runtime_validation_failed",
        "plan_executed",
        "plan_discarded",
    )


@pytest.mark.asyncio
async def test_second_approval_after_completion_is_safe(monkeypatch, sandbox, codegen_stub):
    """Approving twice must not re-run anything (stores are consumed)."""
    supervisor = AssistantSupervisor()
    await _stream(supervisor, _RAG_GOAL, "rw-d1")
    await _stream(supervisor, _STRUCTURED_REPLY, "rw-d2")
    await _stream(supervisor, "approve plan", "rw-d3")

    from tools.tool_router import ToolRouter

    monkeypatch.setattr(
        ToolRouter, "run", staticmethod(lambda t, a, p=None: {"success": True, "output": "ok"})
    )
    first = _final(await _stream(supervisor, "approve", "rw-d4"))
    assert first["status"] == "completed"
    assert action_store.get(_SESSION) is None and plan_store.get(_SESSION) is None

    class _ExecStub:
        async def run(self, goal, mode=None, **kwargs):
            return {
                "run_id": "x",
                "status": "completed",
                "decision": "execution_completed",
                "mode": "execution",
                "message": "ran",
                "final_answer": "ran",
                "sources": [],
                "artifacts": [],
                "approval_summary": None,
                "meta": {},
            }

    supervisor.execution = _ExecStub()
    monkeypatch.setattr(
        sup_module, "generate_conversational_answer", lambda goal, history=None: "ok"
    )
    ctx = build_turn_context("approve", session_id=_SESSION, run_id="rw-d5")
    second = await supervisor._dispatch("approve", ctx)
    assert second["decision"] not in ("runtime_validated", "plan_executed")


# ── Runtime ordering: install before smoke test, evidence in order ───────────


def test_runtime_actions_ordered_install_then_smoke():
    plan = ExecutablePlan(
        task_type="execution",
        goal="g",
        requires_plan_approval=True,
        project_dir="generated/p",
        steps=[
            PlanStep(1, "write", "file_tool", "write_file", {"path": "generated/p/main.py"}),
            PlanStep(2, "write", "file_tool", "write_file", {"path": "generated/p/requirements.txt"}),
        ],
    )
    report = ExecutionReport(
        files_written=[
            {"path": "generated/p/main.py", "bytes": 1},
            {"path": "generated/p/requirements.txt", "bytes": 1},
        ]
    )
    actions = build_runtime_actions(plan, report)
    commands = [a["payload"]["command"] for a in actions]
    assert "pip install" in commands[0]
    assert "compileall" in commands[1]

    ran: list[str] = []
    evidence = execute_runtime_validation(
        plan,
        actions,
        generate=lambda **k: "x = 1\n",
        run_tool=lambda t, a, p=None: (ran.append(p["command"]), {"success": True, "output": ""})[1],
    )
    assert ran == commands  # executed in declared order
    assert [c["command"] for c in evidence["commands"]] == commands


def test_runtime_retry_is_bounded():
    plan = ExecutablePlan(
        task_type="execution",
        goal="g",
        requires_plan_approval=True,
        project_dir="generated/p",
        steps=[PlanStep(1, "write", "file_tool", "write_file", {"path": "generated/p/main.py"})],
    )
    actions = build_runtime_actions(
        plan, ExecutionReport(files_written=[{"path": "generated/p/main.py", "bytes": 1}])
    )
    attempts = {"n": 0}

    def _runner(tool, action, payload=None):
        if tool == "file_tool":
            return {"success": True, "output": ""}
        attempts["n"] += 1
        return {"success": False, "output": 'File "main.py": still broken'}

    evidence = execute_runtime_validation(
        plan, actions, generate=lambda **k: "x = 1\n", run_tool=_runner
    )
    assert evidence["status"] == "failed"
    assert attempts["n"] == 2  # initial + exactly one repaired retry, never more
