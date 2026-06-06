# File: backend/tests/test_capability_services.py

import pytest

import app.routes.aira_x as aira_x_routes
from app.capabilities.execution.execution_service import ExecutionService
from app.capabilities.research.research_service import ResearchService
from app.turn_classifier import EXECUTION_MODE, RESEARCH_THEN_EXECUTION_MODE, WEB_RESEARCH_MODE


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
async def test_execution_service_runs_workflow_and_normalizes(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal, run_id):
            return _FakeState(run_id, goal)

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)

    result = await ExecutionService().run("git status", mode=EXECUTION_MODE)

    assert result["mode"] == EXECUTION_MODE
    assert result["status"] == "completed"
    assert result["meta"]["is_multi_question"] is False


@pytest.mark.asyncio
async def test_execution_service_marks_research_then_execution(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal, run_id):
            return _FakeState(run_id, goal)

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)

    result = await ExecutionService().run("make a ppt", mode=RESEARCH_THEN_EXECUTION_MODE)
    assert result["mode"] == RESEARCH_THEN_EXECUTION_MODE


def test_research_service_returns_grounded_shape():
    # LLM is stubbed by conftest; web provider defaults to "none" so there are
    # no live calls. We assert the normalized research result shape.
    result = ResearchService().run("explain vector databases", want_web=True)

    assert result["mode"] == WEB_RESEARCH_MODE
    assert result["status"] == "completed"
    assert result["decision"] == "web_research_completed"
    assert isinstance(result["message"], str) and result["message"].strip()
    assert isinstance(result["sources"], list)
    assert result["meta"]["is_multi_question"] is False
