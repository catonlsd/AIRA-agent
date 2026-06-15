# File: backend/tests/test_streaming.py

import pytest

import app.assistant_supervisor as sup
import app.core.llm as llm_module
import app.routes.aira_x as aira_x_routes
from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.routes.aira_x import AiraXRunRequest, stream_aira_x

# Captured before any per-test monkeypatch so we can test the real stream().
_REAL_STREAM = llm_module.LLMClient.stream


def _fake_stream(self, system, prompt, temperature=0.2):
    for piece in ["Hi ", "there", "!"]:
        yield piece


@pytest.fixture
def stub_stream(monkeypatch):
    monkeypatch.setattr(llm_module.LLMClient, "stream", _fake_stream)


async def _collect(agen):
    return [event async for event in agen]


class _FakeStep:
    def __init__(self, result):
        self.id = 1
        self.title = "Step"
        self.description = "desc"
        self.status = "completed"
        self.assigned_agent = "execution_agent"
        self.tool_name = None
        self.tool_action = None
        self.tool_payload = {}
        self.result = result
        self.error = None

    def model_dump(self):
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "status": self.status, "assigned_agent": self.assigned_agent,
            "tool_name": self.tool_name, "tool_action": self.tool_action,
            "tool_payload": self.tool_payload, "result": self.result, "error": self.error,
        }


class _FakeState:
    def __init__(self, run_id, goal):
        self.run_id = run_id
        self.user_goal = goal
        self.current_step = 1
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.updated_at = "2026-01-01T00:00:00+00:00"
        self.completed_at = "2026-01-01T00:00:00+00:00"
        self.status = "completed"
        self.decision = "completed"
        self.final_answer = f"Ran: {goal}"
        self.plan = [_FakeStep(result=f"Ran: {goal}")]
        self.execution_outputs = []
        self.memory = {"workflow_logs": [], "workflow_summary": {}}


@pytest.mark.asyncio
async def test_stream_turn_chat_emits_tokens_then_final(stub_stream):
    ctx = build_turn_context("hello", session_id="s")
    events = await _collect(AssistantSupervisor().stream_turn(ctx))

    types = [e["type"] for e in events]
    assert types[0] == "trace"
    assert "token" in types
    assert types[-1] == "final"

    tokens = "".join(e["data"]["text"] for e in events if e["type"] == "token")
    assert tokens == "Hi there!"

    final = events[-1]["data"]
    assert final["mode"] == "general_chat"
    assert final["message"] == "Hi there!"
    assert final["session_id"] == "s"


@pytest.mark.asyncio
async def test_stream_turn_execution_emits_final(monkeypatch, stub_stream):
    class FakeWorkflow:
        async def run(self, goal, run_id):
            return _FakeState(run_id, goal)

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)

    ctx = build_turn_context("git status", session_id="s")
    events = await _collect(AssistantSupervisor().stream_turn(ctx))

    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["mode"] == "execution"


@pytest.mark.asyncio
async def test_stream_turn_replays_recorded_phase_sequence(monkeypatch, stub_stream):
    """The real stage journey recorded during dispatch is streamed live as
    ordered `stage` trace events (not just the final), with duplicates collapsed."""
    supervisor = AssistantSupervisor()

    async def fake_dispatch(message, classification, ctx, reasoning=None):
        # Simulate the phases a guided execution turn really records.
        for stage in [
            "executing_workflow",  # duplicate of the pre-dispatch stage → collapsed
            "validation",
            "startup_validation_started",
            "waiting_for_ready",
            "waiting_for_ready",  # consecutive duplicate → collapsed
            "healthcheck_probing",
        ]:
            ctx.trace.event("stage", stage=stage)
        return supervisor._chat_result(classification, "Done.") | {"mode": "execution"}

    monkeypatch.setattr(supervisor, "_dispatch_non_chat", fake_dispatch)

    ctx = build_turn_context("git status", session_id="s")
    events = await _collect(supervisor.stream_turn(ctx))

    stages = [e["data"]["stage"] for e in events if e["type"] == "trace" and e["data"].get("event") == "stage"]
    assert stages == [
        "executing_workflow",
        "validation",
        "startup_validation_started",
        "waiting_for_ready",
        "healthcheck_probing",
    ]
    assert events[-1]["type"] == "final"


@pytest.mark.asyncio
async def test_stream_turn_emits_error_event_without_crashing(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sup, "parse_prompt_for_questions", boom)

    ctx = build_turn_context("hello", session_id="s")
    events = await _collect(sup.AssistantSupervisor().stream_turn(ctx))

    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["data"]["message"]


@pytest.mark.asyncio
async def test_streamed_turn_persists_a_trace(stub_stream):
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("hello", session_id="trace-stream")
    await _collect(supervisor.stream_turn(ctx))

    records = supervisor.tracer.recent(limit=10)
    assert any(r["session_id"] == "trace-stream" for r in records)


@pytest.mark.asyncio
async def test_sse_endpoint_returns_event_stream(stub_stream):
    response = await stream_aira_x(AiraXRunRequest(goal="hello", session_id="s"))

    assert response.media_type == "text/event-stream"

    body = ""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, str) else chunk.decode()

    assert "event: trace" in body
    assert "event: token" in body
    assert "event: final" in body


def test_llm_stream_falls_back_to_generate(monkeypatch):
    # Restore the real stream(), force an unsupported provider, and confirm it
    # falls back to a single generate() chunk.
    monkeypatch.setattr(llm_module.LLMClient, "stream", _REAL_STREAM)
    monkeypatch.setattr(llm_module.settings, "llm_provider", "local")
    monkeypatch.setattr(
        llm_module.LLMClient, "generate", lambda self, s, p, t=0.2: "FALLBACK"
    )

    chunks = list(llm_module.LLMClient().stream("sys", "prompt"))
    assert chunks == ["FALLBACK"]
