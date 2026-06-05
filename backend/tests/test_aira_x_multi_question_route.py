# File: backend/tests/test_aira_x_multi_question_route.py

import pytest

import app.routes.aira_x as aira_x_routes
from app.routes.aira_x import AiraXRunRequest, run_aira_x


@pytest.fixture(autouse=True)
def stub_workflow_store_save(monkeypatch):
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)


@pytest.mark.asyncio
async def test_run_route_single_prompt_returns_clean_single_response(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal: str, run_id: str):
            return _FakeState(
                run_id=run_id,
                user_goal=goal,
                status="completed",
                decision="completed",
                final_answer=f"Handled single prompt: {goal}",
                memory={
                    "workflow_logs": [],
                    "workflow_summary": {},
                    "sources": [{"type": "note", "label": "single-source"}],
                    "artifacts": [{"type": "text", "name": "single.txt"}],
                },
            )

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(goal="Explain what LangGraph is.")
    )

    assert response["status"] == "completed"
    assert response["mode"] == "single_question"
    assert response["message"] == "Handled single prompt: Explain what LangGraph is."
    assert response["final_answer"] == "Handled single prompt: Explain what LangGraph is."
    assert response["meta"]["is_multi_question"] is False
    assert response["meta"]["question_count"] == 1
    assert response["sources"] == [{"type": "note", "label": "single-source"}]
    assert response["artifacts"] == [{"type": "text", "name": "single.txt"}]
    assert response["approval_summary"] is None


@pytest.mark.asyncio
async def test_run_route_multi_question_returns_grouped_response(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal: str, run_id: str):
            return _FakeState(
                run_id=run_id,
                user_goal=goal,
                status="completed",
                decision="completed",
                final_answer=f"Answer for: {goal}",
                memory={
                    "workflow_logs": [],
                    "workflow_summary": {},
                    "sources": [{"type": "qa", "question": goal}],
                    "artifacts": [{"type": "text", "name": f"{goal}.txt"}],
                },
            )

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(
            goal="""
            Answer the following questions:
            1. What is Python?
            2. What is LangGraph?
            3. What is ChromaDB?
            """
        )
    )

    assert response["status"] == "completed"
    assert response["decision"] == "multi_question_completed"
    assert response["mode"] == "multi_question"
    assert response["meta"]["is_multi_question"] is True
    assert response["meta"]["question_count"] == 3
    assert len(response["sub_answers"]) == 3

    assert response["sub_answers"][0]["question"] == "What is Python?"
    assert response["sub_answers"][0]["message"] == "Answer for: What is Python?"
    assert response["sub_answers"][1]["question"] == "What is LangGraph?"
    assert response["sub_answers"][2]["question"] == "What is ChromaDB?"

    assert len(response["sources"]) == 3
    assert len(response["artifacts"]) == 3
    assert response["approval_summary"] is None

    assert "1. What is Python?" in response["final_answer"]
    assert "2. What is LangGraph?" in response["final_answer"]
    assert "3. What is ChromaDB?" in response["final_answer"]


@pytest.mark.asyncio
async def test_run_route_multi_question_preserves_approval_summary(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal: str, run_id: str):
            if "install" in goal.lower():
                return _FakeState(
                    run_id=run_id,
                    user_goal=goal,
                    status="requires_approval",
                    decision="approval_required",
                    final_answer="This action requires approval before execution.",
                    memory={
                        "workflow_logs": [],
                        "workflow_summary": {},
                        "pending_action": goal,
                        "approval_context": {
                            "type": "tool_policy",
                            "tool_name": "shell_tool",
                            "tool_action": "run",
                        },
                        "approval_resolution": {},
                    },
                )

            return _FakeState(
                run_id=run_id,
                user_goal=goal,
                status="completed",
                decision="completed",
                final_answer=f"Completed safely: {goal}",
                memory={
                    "workflow_logs": [],
                    "workflow_summary": {},
                },
            )

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FakeWorkflow)

    response = await run_aira_x(
        AiraXRunRequest(
            goal="""
            Answer the following questions:
            1. What is Python?
            2. Install requests package.
            """
        )
    )

    assert response["status"] == "requires_approval"
    assert response["decision"] == "multi_question_requires_approval"
    assert response["mode"] == "multi_question"
    assert response["meta"]["requires_approval_count"] == 1
    assert response["approval_summary"] is not None
    assert len(response["approval_summary"]) == 1

    approval_item = response["approval_summary"][0]
    assert approval_item["question_number"] == 2
    assert approval_item["question"] == "Install requests package."
    assert approval_item["approval_summary"]["required"] is True
    assert approval_item["approval_summary"]["action"] == "Install requests package."

    assert response["sub_answers"][0]["status"] == "completed"
    assert response["sub_answers"][1]["status"] == "requires_approval"


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