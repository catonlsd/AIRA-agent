# File: backend/tests/test_direct_answers.py
"""Milestone A step 2 — the dedicated direct-answer path: routing, response
contract cleanliness, self-memory honesty, and streaming compatibility."""

import pytest

import app.core.llm as llm_module
from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.llm_answer_service import (
    SELF_MEMORY_SYSTEM_PROMPT,
    DirectAnswerService,
    offline_self_memory_message,
)
from app.supervisor_reasoning import reason_about_turn
from app.turn_classifier import (
    EXECUTION_MODE,
    GENERAL_CHAT_MODE,
    RESEARCH_THEN_EXECUTION_MODE,
    SELF_MEMORY_MODE,
    classify_turn,
)

_HISTORY = [
    {"role": "user", "content": "Hi, I'm Mokshit and I'm building AIRA-X."},
    {"role": "assistant", "content": "Nice to meet you, Mokshit!"},
]


# ── Routing: conversational turns never hit execution ────────────────────────


@pytest.mark.parametrize("greeting", ["hello", "hey there", "namaste"])
def test_greetings_route_to_general_chat(greeting):
    assert classify_turn(greeting).mode == GENERAL_CHAT_MODE


@pytest.mark.parametrize("prompt", ["who are you", "what can you do"])
def test_identity_routes_to_general_chat(prompt):
    assert classify_turn(prompt).mode == GENERAL_CHAT_MODE


@pytest.mark.parametrize("prompt", ["do you know me", "what do you remember about me"])
def test_self_memory_routes_to_self_memory(prompt):
    assert classify_turn(prompt).mode == SELF_MEMORY_MODE


def test_knowledge_question_avoids_execution():
    reasoning = reason_about_turn("explain Python")
    assert reasoning.selected_route == GENERAL_CHAT_MODE
    assert reasoning.needs_clarification is False


def test_execution_requests_still_route_to_execution():
    assert classify_turn("git push").mode in (EXECUTION_MODE, RESEARCH_THEN_EXECUTION_MODE)
    assert classify_turn("Make a PPT on renewable energy.").mode == RESEARCH_THEN_EXECUTION_MODE


# ── Supervisor wiring + response contract ────────────────────────────────────


@pytest.mark.asyncio
async def test_general_chat_answers_through_direct_service(monkeypatch):
    supervisor = AssistantSupervisor()
    called = {}

    class _Svc(DirectAnswerService):
        def answer(self, goal, *, mode, history=None, preferences=None):
            called["goal"], called["mode"] = goal, mode
            return "Hi! How can I help?"

    supervisor.answers = _Svc()
    ctx = build_turn_context("hello", session_id="da-1", run_id="da-1")
    result = await supervisor._dispatch("hello", ctx)

    assert called == {"goal": "hello", "mode": GENERAL_CHAT_MODE}
    # Routed mode preserved; clean contract; no execution noise.
    assert result["mode"] == GENERAL_CHAT_MODE
    assert result["mode"] != "single_question"
    assert result["decision"] == "general_chat_completed"
    assert result["status"] == "completed"
    assert result["sources"] == []
    assert result["artifacts"] == []
    assert result["meta"]["turn_classification"]["mode"] == GENERAL_CHAT_MODE


@pytest.mark.asyncio
async def test_self_memory_answers_through_direct_service():
    supervisor = AssistantSupervisor()
    ctx = build_turn_context(
        "do you know me", session_id="da-2", run_id="da-2", history=_HISTORY
    )
    result = await supervisor._dispatch("do you know me", ctx)

    assert result["mode"] == SELF_MEMORY_MODE
    assert result["decision"] == "self_memory_completed"
    assert result["sources"] == []
    assert result["artifacts"] == []


# ── Self-memory honesty ──────────────────────────────────────────────────────


def test_self_memory_prompt_carries_conversation_ungated(monkeypatch):
    """"Who am I" must see the transcript — the chat memory gate would drop it."""
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"], captured["prompt"] = system, prompt
        return "You're Mokshit, building AIRA-X."

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    answer = DirectAnswerService().answer("who am I", mode=SELF_MEMORY_MODE, history=_HISTORY)

    assert captured["system"] == SELF_MEMORY_SYSTEM_PROMPT
    assert "Mokshit" in captured["prompt"]  # transcript present despite "new topic" shape
    assert "memory of this user" in captured["prompt"]  # framed as the user's context
    assert answer == "You're Mokshit, building AIRA-X."


def test_self_memory_honest_offline_fallback(monkeypatch):
    def _boom(self, system, prompt, temperature=0.2):
        raise RuntimeError("no provider")

    monkeypatch.setattr(llm_module.LLMClient, "generate", _boom)
    answer = DirectAnswerService().answer("do you know me", mode=SELF_MEMORY_MODE, history=None)

    # Honest, non-robotic, and makes no personal claims.
    assert "don't know anything about you yet" in answer
    assert "conversation" in answer


def test_self_memory_fallback_acknowledges_existing_conversation():
    message = offline_self_memory_message(_HISTORY)
    assert "this conversation" in message
    # Never fabricates specifics in the offline path.
    assert "Mokshit" not in message


# ── Product-grounded meta answers (no generic chatbot fluff) ─────────────────

_FLUFF = (
    "advanced nlp",
    "knowledge graph",
    "improved contextual understanding",
    "thank you for the opportunity",
    "as an ai language model",
)

_META_PROMPTS = [
    "who are you?",
    "what can you do?",
    "what do you need to improve?",
    "As your creator, what additions do you need in your architecture so that you can work more precisely?",
    "how can you become more precise?",
]


def test_meta_question_detection():
    from app.product_manifest import is_product_meta_question

    for prompt in _META_PROMPTS:
        assert is_product_meta_question(prompt), prompt
    # Normal questions must NOT take the meta path.
    assert not is_product_meta_question("what is Python?")
    assert not is_product_meta_question("explain LangGraph")
    assert not is_product_meta_question("can you improve my essay")
    assert not is_product_meta_question("how do you handle errors in Python")


@pytest.mark.parametrize("prompt", _META_PROMPTS)
def test_meta_answers_are_product_grounded_offline(monkeypatch, prompt):
    """Even with no model, self-answers come from the manifest: real system
    areas, zero generic fluff, zero gratitude boilerplate."""

    def _boom(self, system, p, temperature=0.2):
        raise RuntimeError("no provider")

    monkeypatch.setattr(llm_module.LLMClient, "generate", _boom)
    answer = DirectAnswerService().answer(prompt, mode=GENERAL_CHAT_MODE)

    lowered = answer.lower()
    for phrase in _FLUFF:
        assert phrase not in lowered, f"fluff phrase leaked: {phrase}"
    # Grounded in actual AIRA-X product areas.
    assert any(
        area in lowered
        for area in ("supervisor", "chromadb", "runtime validation", "execution", "plan executor")
    ), answer


def test_meta_prompt_carries_manifest_and_style_rules(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"], captured["prompt"] = system, prompt
        return "Grounded answer."

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    answer = DirectAnswerService().answer(
        "what additions do you need in your architecture?", mode=GENERAL_CHAT_MODE
    )

    system = captured["system"]
    # Real product truth injected.
    assert "ChromaDB" in system
    assert "runtime validation" in system.lower()
    assert "supervisor" in system.lower()
    # Style rules enforced in the instructions.
    assert "advanced NLP" in system  # explicitly banned by name
    assert "No gratitude" in system or "no gratitude" in system.lower()
    assert answer == "Grounded answer."


def test_meta_stream_uses_manifest_prompt(monkeypatch):
    captured = {}

    def _fake_stream(self, system, prompt, temperature=0.2):
        captured["system"] = system
        yield "grounded"

    monkeypatch.setattr(llm_module.LLMClient, "stream", _fake_stream)
    pieces = list(
        DirectAnswerService().stream("what can you do?", mode=GENERAL_CHAT_MODE)
    )
    assert pieces == ["grounded"]
    assert "ChromaDB" in captured["system"]


def test_meta_questions_keep_general_chat_mode():
    for prompt in _META_PROMPTS:
        assert classify_turn(prompt).mode == GENERAL_CHAT_MODE, prompt


def test_normal_knowledge_question_bypasses_meta_path(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        return "Python is a programming language."

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    DirectAnswerService().answer("what is Python?", mode=GENERAL_CHAT_MODE)
    # Uses the persona path, not the manifest path.
    assert "PRODUCT TRUTH" not in captured["system"]


# ── Streaming compatibility ──────────────────────────────────────────────────


def test_direct_answer_stream_uses_mode_specific_prompt(monkeypatch):
    captured = {}

    def _fake_stream(self, system, prompt, temperature=0.2):
        captured["system"] = system
        yield "It's "
        yield "you!"

    monkeypatch.setattr(llm_module.LLMClient, "stream", _fake_stream)

    pieces = list(
        DirectAnswerService().stream("who am I", mode=SELF_MEMORY_MODE, history=_HISTORY)
    )
    assert pieces == ["It's ", "you!"]
    assert captured["system"] == SELF_MEMORY_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_streamed_self_memory_turn_keeps_event_grammar(monkeypatch):
    def _fake_stream(self, system, prompt, temperature=0.2):
        yield "Hello "
        yield "again!"

    monkeypatch.setattr(llm_module.LLMClient, "stream", _fake_stream)

    supervisor = AssistantSupervisor()
    ctx = build_turn_context("do you know me", session_id="da-3", run_id="da-3", history=_HISTORY)
    events = [event async for event in supervisor.stream_turn(ctx)]

    types = [e["type"] for e in events]
    assert types[0] == "trace"
    assert types[-1] == "final"
    tokens = [e["data"]["text"] for e in events if e["type"] == "token"]
    assert tokens == ["Hello ", "again!"]
    final = events[-1]["data"]
    assert final["mode"] == SELF_MEMORY_MODE
    assert final["message"] == "Hello again!"
