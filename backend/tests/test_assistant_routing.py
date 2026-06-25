# File: backend/tests/test_assistant_routing.py

import pytest

from app.routes.assistant import (
    classify_message,
    is_casual_smalltalk,
    normalize_message_text,
)


@pytest.mark.parametrize(
    "message",
    ["hola", "aloha", "namaste", "hey there", "greetings", "how are you", "what are you doing"],
)
def test_casual_smalltalk_is_detected(message):
    assert is_casual_smalltalk(normalize_message_text(message)) is True


@pytest.mark.parametrize(
    "message",
    ["what is python", "run command ls", "summarize the document", "latest ai news"],
)
def test_non_smalltalk_is_not_flagged(message):
    assert is_casual_smalltalk(normalize_message_text(message)) is False


@pytest.mark.parametrize(
    "message",
    [
        "what is python",
        "explain recursion to me",
        "write a haiku about the sea",
        "who painted the mona lisa",
    ],
)
def test_general_knowledge_answers_directly_not_via_web(message):
    # The whole point of the fix: ordinary questions should be answered
    # directly by the model, not forced through a web search.
    assert classify_message(message, use_web=True) == "general_answer"


@pytest.mark.parametrize(
    "message",
    [
        "what is the latest news on ai",
        "what's the weather today",
        "current bitcoin price right now",
    ],
)
def test_time_sensitive_queries_route_to_web(message):
    assert classify_message(message, use_web=True) == "web_research"


def test_execution_request_routes_to_workflow():
    assert classify_message("run command ls -la", use_web=True) == "execution_workflow"


def test_document_request_routes_to_document_research():
    assert classify_message("summarize the document", use_web=True) == "document_research"


def test_workflow_followup_is_detected():
    assert classify_message("show me the previous output", use_web=True) == "workflow_followup"
