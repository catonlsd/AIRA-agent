# File: backend/tests/test_assistant_supervisor_flip.py
"""
/assistant/run is now served by the unified supervisor while preserving the
existing AssistantRunResponse contract, with the legacy engine behind a flag and
as an automatic fallback.
"""

import pytest

import app.routes.aira_x as aira_x_routes
import app.routes.assistant as assistant_routes
from app.db.database import SessionLocal, init_db
from app.routes.assistant import AssistantRunRequest, run_assistant

VALID_RESPONSE_TYPES = {
    "casual_chat", "capability_help", "general_answer", "document_research",
    "web_research", "execution_result", "approval_required", "workflow_followup",
    "multi_task", "clarification", "error",
}


@pytest.fixture
def db():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


async def _run(message: str, db, **kwargs):
    return await run_assistant(AssistantRunRequest(message=message, **kwargs), db)


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


# ── per-mode response_type mapping ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_chat(db):
    r = await _run("hello there", db)
    assert r.response_type == "casual_chat"
    assert r.answer.strip()
    assert r.metadata.get("engine") == "supervisor"


@pytest.mark.asyncio
async def test_document_qa(db):
    r = await _run("based on the document I uploaded, what is the main conclusion?", db)
    assert r.response_type == "document_research"
    assert r.metadata.get("engine") == "supervisor"


@pytest.mark.asyncio
async def test_web_research(db):
    r = await _run("research the latest AI trends in healthcare", db)
    assert r.response_type == "web_research"


@pytest.mark.asyncio
async def test_execution(db, monkeypatch):
    class FakeWorkflow:
        async def run(self, goal, run_id):
            return _FakeState(run_id, goal)

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)

    r = await _run("run git status to show the repository state", db)
    assert r.response_type == "execution_result"
    assert r.workflow is not None
    assert r.workflow.get("run_id")


@pytest.mark.asyncio
async def test_no_evidence_document_fallback(db):
    r = await _run("according to the document, explain quantum chromodynamics in detail", db)
    assert r.response_type == "document_research"
    assert r.metadata.get("has_evidence") is False
    # Document-first now escalates honestly: the answer is clearly marked as
    # coming from broader research because the files were insufficient.
    assert "don't appear to contain enough information" in r.answer.lower()
    assert r.metadata.get("answered_from") in ("web_fallback", "insufficient_documents")
    assert r.citations == []


# ── contract compatibility ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_response_type_compatibility(db):
    for message in [
        "hello",
        "research the latest news on AI",
        "based on the document what is the summary",
    ]:
        r = await _run(message, db)
        assert r.response_type in VALID_RESPONSE_TYPES
        # Contract shape preserved.
        assert isinstance(r.answer, str)
        assert isinstance(r.citations, list)
        assert isinstance(r.metadata, dict)


# ── fallback path ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_to_legacy_when_supervisor_fails(db, monkeypatch):
    async def _boom(self, ctx):
        raise RuntimeError("supervisor unavailable")

    monkeypatch.setattr(assistant_routes.AssistantSupervisor, "run_turn", _boom)

    r = await _run("hello there", db)
    # Still answered, via the legacy engine (which does not tag engine=supervisor).
    assert r.response_type in VALID_RESPONSE_TYPES
    assert r.answer.strip()
    assert r.metadata.get("engine") != "supervisor"


@pytest.mark.asyncio
async def test_flag_off_uses_legacy(db, monkeypatch):
    monkeypatch.setenv("AIRA_ASSISTANT_SUPERVISOR", "0")
    r = await _run("hello there", db)
    assert r.response_type in VALID_RESPONSE_TYPES
    assert r.metadata.get("engine") != "supervisor"
