# File: backend/tests/test_memory_architecture.py
"""Richer memory architecture: ownership-scoped preference memory, ephemeral
session memory, a conservative write policy, behaviour-shaping reads, and honest
self-memory answers. No cross-owner leakage; the current turn always wins."""

import pytest

import app.core.llm as llm_module
from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.llm_answer_service import DirectAnswerService, offline_self_memory_message
from app.memory.preference_memory import PreferenceMemory, preference_memory
from app.memory.preference_policy import (
    artifact_style_hint,
    build_style_directive,
    extract_preferences,
)
from app.memory.session_memory import SessionMemory, session_memory
from app.turn_classifier import GENERAL_CHAT_MODE, SELF_MEMORY_MODE


# ── Write policy: selective + intentional ────────────────────────────────────


def test_explicit_preferences_are_extracted():
    assert extract_preferences("Please keep answers concise") == {"answer_length": "concise"}
    assert extract_preferences("I prefer code-first answers") == {"answer_style": "code_first"}
    assert extract_preferences("No bullet points please") == {"answer_format": "prose"}
    assert extract_preferences("I prefer clean professional PPTs") == {"artifact_style": "clean_professional"}


def test_one_off_statements_are_not_stored():
    # Questions and incidental word use must never become preferences.
    assert extract_preferences("What is the capital of France?") == {}
    assert extract_preferences("Tell me about bullet trains") == {}
    assert extract_preferences("Explain how PPT files are structured") == {}
    assert extract_preferences("") == {}


def test_only_catalogue_keys_can_be_written():
    # There is no rule that stores names/identity/arbitrary facts.
    assert extract_preferences("My name is Jordan and I work at Acme") == {}
    assert extract_preferences("Remember that my password is hunter2") == {}


# ── Preference memory: durable + owner-scoped ────────────────────────────────


def test_preferences_do_not_leak_across_owners():
    preference_memory.set("alice", "answer_length", "concise")
    assert preference_memory.get("alice") == {"answer_length": "concise"}
    assert preference_memory.get("bob") == {}  # strict isolation


def test_preference_set_is_upsert():
    preference_memory.set("u", "answer_length", "concise")
    preference_memory.set("u", "answer_length", "detailed")
    assert preference_memory.get("u") == {"answer_length": "detailed"}


def test_clear_is_owner_scoped():
    preference_memory.set("a", "headings", "sparse")
    preference_memory.set("b", "headings", "sparse")
    preference_memory.clear("a")
    assert preference_memory.get("a") == {}
    assert preference_memory.get("b") == {"headings": "sparse"}


def test_preference_memory_is_durable_across_instances():
    PreferenceMemory().set("dur", "answer_style", "code_first")
    # A separate instance == a separate process; the value is read from the DB.
    assert PreferenceMemory().get("dur") == {"answer_style": "code_first"}


# ── Session memory: ephemeral + (owner, session)-scoped ──────────────────────


def test_session_memory_is_scoped_by_owner_and_session():
    mem = SessionMemory()
    mem.note("alice", "s1", "last_request", "build a RAG app")
    assert mem.get("alice", "s1") == {"last_request": "build a RAG app"}
    assert mem.get("bob", "s1") == {}      # owner isolation
    assert mem.get("alice", "s2") == {}    # session isolation


# ── Read/apply policy: behaviour changes, current turn wins ──────────────────


def test_style_directive_reflects_saved_preferences():
    directive = build_style_directive({"answer_length": "concise", "answer_style": "code_first"})
    assert "concise" in directive
    assert "code" in directive


def test_style_directive_states_current_turn_precedence():
    directive = build_style_directive({"answer_length": "concise"})
    assert "current message" in directive and "precedence" in directive


def test_no_directive_when_no_relevant_preferences():
    assert build_style_directive({}) == ""
    # Artifact-only prefs don't add an answer-style directive.
    assert build_style_directive({"artifact_style": "clean_professional"}) == ""


def test_saved_preference_changes_general_chat_system_prompt(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        return "ok"

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    DirectAnswerService().answer(
        "tell me about python", mode=GENERAL_CHAT_MODE,
        preferences={"answer_length": "concise"},
    )
    assert "concise" in captured["system"]  # saved preference shaped the prompt


def test_artifact_style_hint_maps_preference():
    assert "clean" in artifact_style_hint({"artifact_style": "clean_professional"}).lower()
    assert artifact_style_hint({}) == ""


# ── Self-memory answers: honest, no hallucination ────────────────────────────


def test_self_memory_offline_with_no_context_is_honest():
    msg = offline_self_memory_message(history=None, preferences={})
    assert "don't know anything about you yet" in msg.lower() or "only remember" in msg.lower()


def test_self_memory_offline_reports_saved_preferences():
    msg = offline_self_memory_message(history=None, preferences={"answer_length": "concise"})
    assert "concise" in msg.lower()
    # Honest scope: nothing invented beyond the saved preference.
    assert "name" not in msg.lower()


def test_self_memory_prompt_includes_saved_preferences(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["prompt"] = prompt
        return "You've asked me to keep answers concise."

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    DirectAnswerService().answer(
        "what do you remember about me?", mode=SELF_MEMORY_MODE,
        preferences={"answer_length": "concise"},
    )
    assert "concise" in captured["prompt"].lower()


# ── Supervisor integration: prime, store, scope ──────────────────────────────


@pytest.mark.asyncio
async def test_supervisor_remembers_and_scopes_preference(monkeypatch):
    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        return "Understood."

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)
    supervisor = AssistantSupervisor()

    # Turn 1 (owner alice): state a preference -> it is remembered, owner-scoped.
    ctx1 = build_turn_context("From now on, keep answers concise.", session_id="alice", owner="alice")
    await supervisor.run_turn(ctx1)
    assert preference_memory.get("alice") == {"answer_length": "concise"}
    assert preference_memory.get("bob") == {}  # never leaked to another owner

    # Turn 2 (owner alice): a later chat turn applies the saved preference.
    ctx2 = build_turn_context("tell me about python", session_id="alice", owner="alice")
    await supervisor.run_turn(ctx2)
    assert "concise" in captured["system"]


@pytest.mark.asyncio
async def test_supervisor_does_not_store_one_off_chatter(monkeypatch):
    monkeypatch.setattr(
        llm_module.LLMClient, "generate", lambda self, system, prompt, temperature=0.2: "Hi!"
    )
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("what's a good name for a bullet train?", session_id="u", owner="u")
    await supervisor.run_turn(ctx)
    assert preference_memory.get("u") == {}  # nothing creepy or incidental stored
