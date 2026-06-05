# File: backend/tests/test_aira_x_multi_question_mixed_batch.py

import pytest

import app.routes.aira_x as aira_x_routes
from app.routes.aira_x import AiraXRunRequest, run_aira_x


@pytest.fixture(autouse=True)
def stub_workflow_store_save(monkeypatch):
    monkeypatch.setattr(aira_x_routes.WorkflowStore, "save", lambda state: None)


@pytest.mark.asyncio
async def test_mixed_multi_question_batch_preserves_each_item_type(monkeypatch):
    class FakeWorkflow:
        async def run(self, goal: str, run_id: str):
            normalized_goal = goal.strip().lower()

            if "install requests package" in normalized_goal:
                return _FakeState(
                    run_id=run_id,
                    user_goal=goal,
                    status="requires_approval",
                    decision="approval_required",
                    final_answer="This action requires approval before execution.",
                    memory={
                        "workflow_logs": [],
                        "workflow_summary": {},
                        "pending_action": goal.strip(),
                        "approval_context": {
                            "type": "tool_policy",
                            "tool_name": "shell_tool",
                            "tool_action": "run",
                        },
                        "approval_resolution": {},
                    },
                )

            if "latest ai trends" in normalized_goal:
                return _FakeState(
                    run_id=run_id,
                    user_goal=goal,
                    status="completed",
                    decision="completed",
                    final_answer="Here are the latest AI trends I found.",
                    memory={
                        "workflow_logs": [],
                        "workflow_summary": {},
                        "web_sources": [
                            {
                                "type": "web",
                                "title": "AI Trends Report",
                                "url": "https://example.com/ai-trends",
                            }
                        ],
                    },
                )

            return _FakeState(
                run_id=run_id,
                user_goal=goal,
                status="completed",
                decision="completed",
                final_answer="Hello! I’m AIRA-X, and I can help with research and execution tasks.",
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
            1. Hello, who are you?
            2. Install requests package.
            3. What are the latest AI trends?
            """
        )
    )

    assert response["status"] == "requires_approval"
    assert response["decision"] == "multi_question_requires_approval"
    assert response["mode"] == "multi_question"

    assert response["meta"]["is_multi_question"] is True
    assert response["meta"]["question_count"] == 3
    assert response["meta"]["completed_count"] == 2
    assert response["meta"]["requires_approval_count"] == 1
    assert response["meta"]["failed_count"] == 0

    assert len(response["sub_answers"]) == 3

    first = response["sub_answers"][0]
    second = response["sub_answers"][1]
    third = response["sub_answers"][2]

    assert first["question"] == "Hello, who are you?"
    assert first["status"] == "completed"
    assert "aira-x" in first["message"].lower()

    assert second["question"] == "Install requests package."
    assert second["status"] == "requires_approval"
    assert second["approval_summary"] is not None
    assert second["approval_summary"]["required"] is True

    assert third["question"] == "What are the latest AI trends?"
    assert third["status"] == "completed"
    assert third["sources"] == [
        {
            "type": "web",
            "title": "AI Trends Report",
            "url": "https://example.com/ai-trends",
        }
    ]

    assert response["approval_summary"] is not None
    assert len(response["approval_summary"]) == 1
    assert response["approval_summary"][0]["question_number"] == 2

    assert len(response["sources"]) == 1
    assert response["sources"][0]["type"] == "web"

    assert "1. Hello, who are you?" in response["final_answer"]
    assert "2. Install requests package." in response["final_answer"]
    assert "3. What are the latest AI trends?" in response["final_answer"]


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