# File: backend/tests/test_operations.py
"""Operations baseline: config fail-fast and correlated lifecycle logging."""

import json
import logging

import pytest

from app.assistant_supervisor import AssistantSupervisor
from app.context_builder import build_turn_context
from app.core.config import Settings


# ── Config validation fails fast and clearly ─────────────────────────────────


def test_missing_provider_key_fails_fast(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = Settings(llm_provider="groq", groq_api_key=None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is required"):
        settings.validate_runtime_config()


def test_present_provider_key_passes():
    settings = Settings(llm_provider="groq", groq_api_key="gsk_test")
    settings.validate_runtime_config()  # no raise


# ── Lifecycle logs carry correlation ids ─────────────────────────────────────


@pytest.mark.asyncio
async def test_supervisor_lifecycle_logs_are_structured_and_correlated(caplog):
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("hello", session_id="ops-session", run_id="ops-run")

    with caplog.at_level(logging.INFO, logger="aira_x.supervisor"):
        await supervisor._dispatch("hello", ctx)
        # run_turn persists the trace + emits turn_completed; _dispatch alone
        # emits route_chosen. Both must be parseable JSON with session ids.

    events = []
    for record in caplog.records:
        if record.name != "aira_x.supervisor":
            continue
        payload = json.loads(record.getMessage())  # structured, parseable
        events.append(payload)
        assert payload["session_id"] == "ops-session"
        assert payload["turn_id"]

    assert any(e["event"] == "route_chosen" for e in events)
    route = next(e for e in events if e["event"] == "route_chosen")
    assert route["mode"] == "general_chat"


@pytest.mark.asyncio
async def test_turn_completed_log_includes_run_id(caplog):
    supervisor = AssistantSupervisor()
    ctx = build_turn_context("hello", session_id="ops-session-2", run_id="ops-run-2")

    with caplog.at_level(logging.INFO, logger="aira_x.supervisor"):
        response = await supervisor.run_turn(ctx)

    completed = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "aira_x.supervisor"
        and '"turn_completed"' in r.getMessage()
    ]
    assert completed, "turn_completed must be logged"
    assert completed[-1]["run_id"] == response.run_id
    assert completed[-1]["mode"] == response.mode
    assert completed[-1]["status"] == response.status
    assert completed[-1]["latency_ms"] >= 0
