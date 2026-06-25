# File: backend/tests/test_conversational_chat.py

import pytest

import app.conversation as conversation
import app.routes.aira_x as aira_x_routes
from app.conversation import (
    AIRA_X_PERSONA_SYSTEM_PROMPT,
    _build_history_prompt,
    classify_memory_use,
)
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


@pytest.mark.asyncio
async def test_conversation_history_is_included_in_the_prompt(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        # The same client is used by the intent router; route the ambiguous
        # follow-up to a conversational mode, then capture the answer prompt.
        if "intent router" in system.lower():
            return "self_memory"
        captured["prompt"] = prompt
        return "It was the folded-hands emoji."

    monkeypatch.setattr(conversation.LLMClient, "generate", _capture)

    history = [
        {"role": "user", "content": "who was lincoln"},
        {"role": "assistant", "content": "Abraham Lincoln was the 16th US President. 🙏"},
    ]
    response = await run_aira_x(
        AiraXRunRequest(goal="what emoji did you use in the last answer?", history=history)
    )

    # The prior assistant turn (with the emoji) must reach the model.
    assert "Abraham Lincoln was the 16th US President" in captured["prompt"]
    assert "what emoji did you use in the last answer?" in captured["prompt"]
    assert response["message"] == "It was the folded-hands emoji."


def test_persona_prompt_forbids_robotic_formatting():
    prompt = AIRA_X_PERSONA_SYSTEM_PROMPT.lower()

    # The prompt must steer the model away from the encyclopedic, headed,
    # essay-style replies we are fixing.
    assert "do not add headings" in prompt
    assert "match the user's tone and length" in prompt
    assert "never answer a one-word greeting with an essay" in prompt
    assert "any language" in prompt


# ── Conversational memory behaviour ──────────────────────────────────────────

# A prior conversation about an unrelated topic (Zoom).
_ZOOM_HISTORY = [
    {"role": "user", "content": "How do I start a Zoom meeting?"},
    {"role": "assistant", "content": "Open Zoom, sign in, and click New Meeting to start."},
]


def test_persona_forbids_narrating_memory():
    prompt = AIRA_X_PERSONA_SYSTEM_PROMPT.lower()
    # Must explicitly discourage narrating prior topics on a new question.
    assert "since we were discussing" in prompt
    assert "use it silently" in prompt or "do not mention" in prompt


def test_unrelated_topic_switch_is_new_topic():
    # The reported bug: a fresh, self-contained question after an unrelated topic.
    assert classify_memory_use("What are the types of soil?", _ZOOM_HISTORY) == "new_topic"

    # New-topic turns must NOT carry the prior context into the prompt, so the
    # model cannot leak or narrate "since we were discussing Zoom...".
    prompt = _build_history_prompt("What are the types of soil?", _ZOOM_HISTORY)
    assert "Zoom" not in prompt
    assert prompt.strip().endswith("What are the types of soil?")


def test_continuation_request_keeps_memory():
    assert classify_memory_use("tell me more", _ZOOM_HISTORY) == "continuation"
    assert classify_memory_use("continue", _ZOOM_HISTORY) == "continuation"

    prompt = _build_history_prompt("put that in bullet points", _ZOOM_HISTORY)
    assert "Zoom" in prompt


def test_explicit_memory_recall_keeps_memory():
    assert classify_memory_use("what did you just say?", _ZOOM_HISTORY) == "explicit_recall"

    prompt = _build_history_prompt("what did we talk about earlier?", _ZOOM_HISTORY)
    assert "Zoom" in prompt


def test_followup_question_keeps_memory():
    assert classify_memory_use("what about the mobile app?", _ZOOM_HISTORY) == "follow_up"
    assert classify_memory_use("why is that?", _ZOOM_HISTORY) == "follow_up"

    prompt = _build_history_prompt("what about the mobile app?", _ZOOM_HISTORY)
    assert "Zoom" in prompt


def test_no_history_is_always_new_topic():
    assert classify_memory_use("tell me more", []) == "new_topic"
    assert classify_memory_use("what did you just say?", None) == "new_topic"
