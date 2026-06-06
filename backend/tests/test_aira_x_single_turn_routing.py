# File: backend/tests/test_aira_x_single_turn_routing.py

import pytest

import app.routes.aira_x as aira_x_routes
from app.routes.aira_x import AiraXRunRequest, run_aira_x


@pytest.fixture(autouse=True)
def stub_workflow_store_save(monkeypatch):
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)


@pytest.mark.asyncio
async def test_general_chat_route_does_not_use_workflow(monkeypatch):
    class FailingWorkflow:
        def __init__(self):
            raise AssertionError("General chat should not instantiate the execution workflow.")

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FailingWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Hello, who are you?")
    )

    assert response["status"] == "completed"
    assert response["decision"] == "general_chat_completed"
    assert response["mode"] == "general_chat"
    assert "aira-x" in response["message"].lower()
    assert response["sources"] == []
    assert response["artifacts"] == []
    assert response["approval_summary"] is None
    assert response["meta"]["is_multi_question"] is False
    assert response["meta"]["question_count"] == 1
    assert response["meta"]["turn_classification"]["mode"] == "general_chat"


@pytest.mark.asyncio
async def test_self_memory_route_does_not_use_workflow(monkeypatch):
    class FailingWorkflow:
        def __init__(self):
            raise AssertionError("Self-memory turns should not instantiate the execution workflow.")

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FailingWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Do you know me?")
    )

    assert response["status"] == "completed"
    assert response["decision"] == "self_memory_completed"
    assert response["mode"] == "self_memory"
    assert "only know what you share" in response["message"].lower()
    assert response["sources"] == []
    assert response["artifacts"] == []
    assert response["approval_summary"] is None
    assert response["meta"]["turn_classification"]["mode"] == "self_memory"


@pytest.mark.asyncio
async def test_document_qa_route_returns_placeholder_without_workflow(monkeypatch):
    class FailingWorkflow:
        def __init__(self):
            raise AssertionError("Document QA placeholder route should not instantiate the execution workflow.")

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FailingWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Based on the document I uploaded, what is the main conclusion?")
    )

    assert response["status"] == "completed"
    assert response["decision"] == "document_qa_routed"
    assert response["mode"] == "document_qa"
    assert "document-first analysis" in response["message"].lower()
    assert response["sources"] == []
    assert response["artifacts"] == []
    assert response["approval_summary"] is None
    assert response["meta"]["turn_classification"]["mode"] == "document_qa"


@pytest.mark.asyncio
async def test_web_research_route_uses_research_service_not_workflow(monkeypatch):
    class FailingWorkflow:
        def __init__(self):
            raise AssertionError("Web research should not instantiate the execution workflow.")

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FailingWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Research the latest AI trends in healthcare.")
    )

    # Web research now flows through the ResearchService capability (real answer
    # generation + citations), not a placeholder and not the execution workflow.
    assert response["status"] == "completed"
    assert response["decision"] == "web_research_completed"
    assert response["mode"] == "web_research"
    assert isinstance(response["message"], str) and response["message"].strip()
    assert response["artifacts"] == []
    assert response["approval_summary"] is None
    assert response["meta"]["turn_classification"]["mode"] == "web_research"


@pytest.mark.asyncio
async def test_execution_route_still_uses_workflow(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal: str, run_id: str):
            return _FakeState(
                run_id=run_id,
                user_goal=goal,
                status="completed",
                decision="completed",
                final_answer=f"Execution completed for: {goal}",
                memory={
                    "workflow_logs": [],
                    "workflow_summary": {},
                    "sources": [{"type": "execution", "label": "tool-output"}],
                    "artifacts": [{"type": "text", "name": "execution.txt"}],
                },
            )

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Read file backend/main.py")
    )

    assert response["status"] == "completed"
    assert response["mode"] == "execution"
    assert response["message"] == "Execution completed for: Read file backend/main.py"
    assert response["final_answer"] == "Execution completed for: Read file backend/main.py"
    assert response["sources"] == [{"type": "execution", "label": "tool-output"}]
    assert response["artifacts"] == [{"type": "text", "name": "execution.txt"}]
    assert response["approval_summary"] is None
    assert response["meta"]["turn_classification"]["mode"] == "execution"


class _FakeStep:
    def __init__(
        self,
        *,
        step_id: int = 1,
        title: str = "Mock Step",
        description: str = "Mock Step Description",
        status: str = "completed",
        assigned_agent: str = "execution_agent",
        tool_name: str | None = None,
        tool_action: str | None = None,
        tool_payload: dict | None = None,
        result: str | None = None,
        error: str | None = None,
    ):
        self.id = step_id
        self.title = title
        self.description = description
        self.status = status
        self.assigned_agent = assigned_agent
        self.tool_name = tool_name
        self.tool_action = tool_action
        self.tool_payload = tool_payload or {}
        self.result = result
        self.error = error

    def model_dump(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "assigned_agent": self.assigned_agent,
            "tool_name": self.tool_name,
            "tool_action": self.tool_action,
            "tool_payload": self.tool_payload,
            "result": self.result,
            "error": self.error,
        }


class _FakeState:
    def __init__(
        self,
        *,
        run_id: str,
        user_goal: str,
        status: str,
        decision: str,
        final_answer: str,
        memory: dict | None = None,
    ):
        self.run_id = run_id
        self.user_goal = user_goal
        self.current_step = 1
        self.created_at = "2026-01-01T00:00:00+00:00"
        self.updated_at = "2026-01-01T00:00:00+00:00"
        self.completed_at = "2026-01-01T00:00:00+00:00"
        self.status = status
        self.decision = decision
        self.final_answer = final_answer
        self.plan = [_FakeStep(result=final_answer)]
        self.execution_outputs = []
        self.memory = memory or {}