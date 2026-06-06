# File: backend/tests/test_hardening.py
"""
Hardening tests from the Phase 1 validation sprint (Phase C bug hunt).

Covers two defects found by stress-testing the real endpoints:
1. Empty / unintelligible input used to fall through to the execution workflow;
   it must ask for clarification instead.
2. Control / null characters in a message must be stripped before reaching the
   LLM, vector store, or trace log.
"""

import pytest

import app.routes.aira_x as aira_x_routes
from app.context_builder import build_turn_context, sanitize_text
from app.routes.aira_x import AiraXRunRequest, run_aira_x


class _FailingWorkflow:
    def __init__(self):
        raise AssertionError("Clarification/empty input must not run the execution workflow.")


@pytest.mark.parametrize("goal", ["", "   ", "\n\t  ", "?!.,"])
@pytest.mark.asyncio
async def test_empty_input_asks_for_clarification_not_execution(goal, monkeypatch):
    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", _FailingWorkflow)

    response = await run_aira_x(AiraXRunRequest(goal=goal))

    assert response["mode"] == "clarification"
    assert response["decision"] == "clarification"
    assert response["status"] == "completed"
    assert "didn't quite catch" in response["message"].lower()


def test_sanitize_strips_control_chars_but_keeps_whitespace():
    assert sanitize_text("hi\x00\x07 there") == "hi there"
    assert sanitize_text("keep\ttab\nnewline\rreturn") == "keep\ttab\nnewline\rreturn"
    assert sanitize_text("") == ""
    assert sanitize_text("normal text") == "normal text"


def test_build_context_sanitizes_message_and_history():
    ctx = build_turn_context(
        "hello\x00world",
        session_id="s",
        history=[{"role": "user", "content": "prev\x07ious"}],
    )
    assert ctx.message == "helloworld"
    assert "\x00" not in ctx.message
    assert ctx.history[0]["content"] == "previous"


@pytest.mark.asyncio
async def test_control_chars_in_message_route_cleanly(monkeypatch):
    # After sanitization "hello\x00\x07 there" -> "hello there" (a greeting).
    monkeypatch.setattr(aira_x_routes, "LangGraphAiraXWorkflow", _FailingWorkflow)
    response = await run_aira_x(AiraXRunRequest(goal="hello\x00\x07 there"))
    assert response["mode"] == "general_chat"
