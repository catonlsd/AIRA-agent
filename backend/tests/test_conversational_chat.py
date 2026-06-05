# File: backend/tests/test_conversational_chat.py

import pytest

import app.conversation as conversation
import app.routes.aira_x as aira_x_routes
from app.conversation import AIRA_X_PERSONA_SYSTEM_PROMPT
from app.routes.aira_x import AiraXRunRequest, run_aira_x


@pytest.fixture(autouse=True)
def fail_if_workflow_used(monkeypatch):
    class FailingWorkflow:
        def __init__(self):
            raise AssertionError("Conversational chat must not run the execution workflow.")

    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", FailingWorkflow)


@pytest.mark.parametrize(
    "greeting",
    ["hola", "aloha", "namaste", "bonjour", "ciao", "greetings", "howdy", "hey there"],
)
@pytest.mark.asyncio
async def test_multilingual_greetings_route_to_conversational_chat(greeting):
    response = await run_aira_x(AiraXRunRequest(goal=greeting))

    assert response["mode"] == "general_chat"
    assert response["decision"] == "general_chat_completed"
    assert response["meta"]["is_multi_question"] is False
    # Answered conversationally (the test LLM stub stands in for a real reply).
    assert isinstance(response["message"], str) and response["message"].strip()


@pytest.mark.asyncio
async def test_conversational_answer_uses_persona_prompt(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        captured["prompt"] = prompt
        return "Hey! 👋 How can I help you today?"

    monkeypatch.setattr(conversation.LLMClient, "generate", _capture)

    response = await run_aira_x(AiraXRunRequest(goal="hey there"))

    assert captured["system"] == AIRA_X_PERSONA_SYSTEM_PROMPT
    assert captured["prompt"] == "hey there"
    assert response["message"] == "Hey! 👋 How can I help you today?"


def test_persona_prompt_forbids_robotic_formatting():
    prompt = AIRA_X_PERSONA_SYSTEM_PROMPT.lower()

    # The prompt must steer the model away from the encyclopedic, headed,
    # essay-style replies we are fixing.
    assert "do not add headings" in prompt
    assert "match the user's tone and length" in prompt
    assert "never answer a one-word greeting with an essay" in prompt
    assert "any language" in prompt
