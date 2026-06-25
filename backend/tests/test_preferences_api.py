# File: backend/tests/test_preferences_api.py
"""Explicit preference-management API: owner-scoped list/set/clear-one/clear-all
over the product-approved catalogue only. Strict ownership; no raw internals."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory.preference_memory import preference_memory

client = TestClient(app)


def _keys(payload: dict) -> set[str]:
    return {entry["key"] for entry in payload["preferences"]}


def _value(payload: dict, key: str):
    return next(e["value"] for e in payload["preferences"] if e["key"] == key)


# ── List: catalogue + current values, human-friendly, no internals ───────────


def test_list_returns_catalogue_with_human_labels():
    resp = client.get("/preferences", params={"session_id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert "answer_length" in _keys(body)
    entry = next(e for e in body["preferences"] if e["key"] == "answer_length")
    assert entry["label"] == "Answer length"
    assert entry["description"]
    assert {o["value"] for o in entry["options"]} == {"concise", "detailed"}
    # Unset preference reads as null, never a raw DB row / internal field.
    assert entry["value"] is None
    assert "is_sensitive" not in entry and "source" not in entry and "id" not in entry


# ── Set / update ─────────────────────────────────────────────────────────────


def test_set_and_update_preference():
    client.put("/preferences", json={"session_id": "alice", "key": "answer_length", "value": "concise"})
    body = client.get("/preferences", params={"session_id": "alice"}).json()
    assert _value(body, "answer_length") == "concise"

    body = client.put(
        "/preferences", json={"session_id": "alice", "key": "answer_length", "value": "detailed"}
    ).json()
    assert _value(body, "answer_length") == "detailed"  # upsert


def test_invalid_key_is_rejected():
    resp = client.put("/preferences", json={"session_id": "alice", "key": "favorite_color", "value": "blue"})
    assert resp.status_code == 400
    assert preference_memory.get("alice") == {}  # nothing stored


def test_invalid_value_is_rejected():
    resp = client.put("/preferences", json={"session_id": "alice", "key": "answer_length", "value": "epic"})
    assert resp.status_code == 400
    assert preference_memory.get("alice") == {}


# ── Clear one / clear all ────────────────────────────────────────────────────


def test_clear_one_preference():
    client.put("/preferences", json={"session_id": "alice", "key": "answer_length", "value": "concise"})
    client.put("/preferences", json={"session_id": "alice", "key": "answer_style", "value": "code_first"})
    body = client.delete("/preferences/answer_length", params={"session_id": "alice"}).json()
    assert _value(body, "answer_length") is None
    assert _value(body, "answer_style") == "code_first"  # the other survives


def test_clear_all_preferences():
    client.put("/preferences", json={"session_id": "alice", "key": "answer_length", "value": "concise"})
    client.put("/preferences", json={"session_id": "alice", "key": "headings", "value": "sparse"})
    body = client.delete("/preferences", params={"session_id": "alice"}).json()
    assert all(e["value"] is None for e in body["preferences"])
    assert preference_memory.get("alice") == {}


# ── Ownership isolation ──────────────────────────────────────────────────────


def test_owner_cannot_see_or_change_another_owners_preferences():
    client.put("/preferences", json={"session_id": "alice", "key": "answer_length", "value": "concise"})
    # Bob's view never shows Alice's value.
    bob = client.get("/preferences", params={"session_id": "bob"}).json()
    assert _value(bob, "answer_length") is None
    # Bob clearing all does not touch Alice.
    client.delete("/preferences", params={"session_id": "bob"})
    assert preference_memory.get("alice") == {"answer_length": "concise"}


# ── Edited preference actually changes behaviour ─────────────────────────────


@pytest.mark.asyncio
async def test_saved_preference_changes_later_answer_behaviour(monkeypatch):
    import app.core.llm as llm_module
    from app.assistant_supervisor import AssistantSupervisor
    from app.context_builder import build_turn_context

    captured = {}

    def _capture(self, system, prompt, temperature=0.2):
        captured["system"] = system
        return "ok"

    monkeypatch.setattr(llm_module.LLMClient, "generate", _capture)

    # Save a preference through the API, then a later turn applies it.
    client.put("/preferences", json={"session_id": "carol", "key": "answer_length", "value": "concise"})
    ctx = build_turn_context("tell me about python", session_id="carol", owner="carol")
    await AssistantSupervisor().run_turn(ctx)
    assert "concise" in captured["system"]

    # Clearing it removes the behavioural effect.
    client.delete("/preferences", params={"session_id": "carol"})
    captured.clear()
    ctx2 = build_turn_context("tell me about rust", session_id="carol", owner="carol")
    await AssistantSupervisor().run_turn(ctx2)
    assert "Saved style preferences" not in captured.get("system", "")
