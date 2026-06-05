# File: backend/tests/test_intent_router.py

import pytest

import app.intent_router as intent_router
from app.intent_router import route_turn
from app.turn_classifier import (
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    WEB_RESEARCH_MODE,
)


class _StubLLM:
    """Stand-in LLM client that returns a fixed classification label."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def generate(self, system: str, prompt: str, temperature: float = 0.2) -> str:
        self.calls += 1
        return self.reply


@pytest.fixture(autouse=True)
def force_llm_configured(monkeypatch):
    # The router only consults the LLM when a provider is configured.
    monkeypatch.setattr(intent_router, "_llm_is_configured", lambda: True)


def test_confident_keyword_match_skips_the_llm():
    stub = _StubLLM("general_chat")

    result = route_turn("git status", llm_client=stub)

    assert result.mode == EXECUTION_MODE
    # High-confidence keyword routing should not waste an LLM call.
    assert stub.calls == 0


def test_ambiguous_prompt_is_resolved_by_llm():
    stub = _StubLLM("general_chat")

    result = route_turn("I'm feeling stuck on my project today, any thoughts?", llm_client=stub)

    assert result.mode == GENERAL_CHAT_MODE
    assert stub.calls == 1


def test_llm_can_route_ambiguous_prompt_to_execution():
    stub = _StubLLM("execution")

    result = route_turn("commit all my changes with a good message", llm_client=stub)

    assert result.mode == EXECUTION_MODE
    assert result.needs_execution is True


def test_llm_label_embedded_in_a_sentence_is_parsed():
    stub = _StubLLM("This looks like web_research to me.")

    result = route_turn("what happened in the markets this week", llm_client=stub)

    assert result.mode == WEB_RESEARCH_MODE


def test_unusable_llm_reply_falls_back_to_execution():
    stub = _StubLLM("i have no idea honestly")

    result = route_turn("do the thing we discussed", llm_client=stub)

    # When the LLM gives nothing usable, route into the workflow rather than
    # silently deflecting to chat.
    assert result.mode == EXECUTION_MODE
    assert result.needs_execution is True


def test_artifact_request_routes_to_research_then_execution_via_keywords():
    stub = _StubLLM("general_chat")

    result = route_turn("Make a PPT on renewable energy", llm_client=stub)

    assert result.mode == RESEARCH_THEN_EXECUTION_MODE
    assert result.artifact_type == "pptx"
    assert stub.calls == 0


def test_no_llm_configured_falls_back_to_execution(monkeypatch):
    monkeypatch.setattr(intent_router, "_llm_is_configured", lambda: False)
    stub = _StubLLM("general_chat")

    result = route_turn("do the thing we discussed", llm_client=stub)

    assert result.mode == EXECUTION_MODE
    assert stub.calls == 0
