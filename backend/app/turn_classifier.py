# File: backend/app/turn_classifier.py

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence


@dataclass(slots=True)
class TurnClassification:
    mode: str
    reason: str
    confidence: float
    needs_research: bool
    needs_execution: bool
    needs_document_analysis: bool
    needs_approval_review: bool
    artifact_type: str | None = None


GENERAL_CHAT_MODE = "general_chat"
SELF_MEMORY_MODE = "self_memory"
DOCUMENT_QA_MODE = "document_qa"
WEB_RESEARCH_MODE = "web_research"
EXECUTION_MODE = "execution"
RESEARCH_THEN_EXECUTION_MODE = "research_then_execution"
CLARIFICATION_MODE = "clarification"


_GENERAL_CHAT_PATTERNS = (
    "hello",
    "hi",
    "hiya",
    "hey",
    "heya",
    "yo",
    "sup",
    "howdy",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "what's up",
    "whats up",
    # Common greetings in other languages — AIRA-X should greet back naturally.
    "hola",
    "aloha",
    "namaste",
    "bonjour",
    "ciao",
    "salut",
    "hallo",
    "ola",
)

_IDENTITY_PATTERNS = (
    "who are you",
    "what can you do",
    "how can you help",
    "what do you do",
    "introduce yourself",
    "tell me about yourself",
)

_SELF_MEMORY_PATTERNS = (
    "do you know me",
    "who am i",
    "what do you know about me",
    "what do you remember about me",
    "do you remember me",
)

_DOCUMENT_REFERENCE_PATTERNS = (
    "based on the document",
    "based on the file",
    "from the document",
    "from the file",
    "according to the document",
    "according to the file",
    "in the document",
    "in the file",
    "in the pdf",
    "from the pdf",
    "uploaded document",
    "uploaded file",
    "the document i uploaded",
    "the file i uploaded",
)

_ARTIFACT_PATTERNS: dict[str, tuple[str, ...]] = {
    "pptx": (
        "ppt",
        "pptx",
        "powerpoint",
        "presentation",
        "slide deck",
        "slides",
    ),
    "docx": (
        "docx",
        "document",
        "report",
        "proposal",
        "write a report",
        "write a document",
    ),
    "xlsx": (
        "xlsx",
        "excel",
        "spreadsheet",
        "sheet",
        "table file",
    ),
}

_EXECUTION_PATTERNS = (
    "run command",
    "execute command",
    "shell command",
    "terminal command",
    "read file",
    "open file",
    "show file",
    "write file",
    "create file",
    "save file",
    "list files",
    "show files",
    "run python",
    "python code",
    "execute python",
    "git status",
    "git diff",
    "git branch",
    "git log",
    "git commit",
    "git push",
    "pip install",
    "install package",
    "npm install",
    "deploy",
)

_HIGH_RISK_EXECUTION_PATTERNS = (
    "pip install",
    "pip uninstall",
    "npm install",
    "npm uninstall",
    "git commit",
    "git push",
    "deploy",
    "docker",
    "vercel",
    "render",
    "railway",
)

_RESEARCH_PATTERNS = (
    "research",
    "search the web",
    "search web",
    "look up",
    "find information",
    "find sources",
    "latest",
    "current",
    "recent",
    "trends",
    "news",
    "compare",
)

_INFORMATION_REQUEST_PATTERNS = (
    "what is",
    "what are",
    "why is",
    "why are",
    "how does",
    "how do",
    "explain",
    "summarize",
    "summarise",
    "tell me about",
    "give me information",
)


def classify_turn(
    prompt: str,
    *,
    has_uploaded_files: bool = False,
    uploaded_file_names: Sequence[str] | None = None,
) -> TurnClassification:
    cleaned_prompt = _normalize_text(prompt)

    # Empty, or no word characters at all (punctuation / symbols / emoji only).
    # \w is Unicode-aware, so real letters in any script still pass through.
    if not cleaned_prompt or not re.search(r"\w", cleaned_prompt):
        return TurnClassification(
            mode=CLARIFICATION_MODE,
            reason="The prompt has no intelligible content after normalization.",
            confidence=1.0,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    artifact_type = _detect_artifact_type(cleaned_prompt)

    # Order matters: actionable/tool intents are checked before the looser
    # conversational greeting heuristic so that prompts like
    # `run python code: print("Hello from AIRA-X")` are not misread as chat
    # just because the word "hello" appears inside a code string.
    if _is_self_memory_question(cleaned_prompt):
        return TurnClassification(
            mode=SELF_MEMORY_MODE,
            reason="The prompt asks about user identity, memory, or prior knowledge of the user.",
            confidence=0.96,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    if _has_explicit_document_reference(cleaned_prompt, uploaded_file_names):
        return TurnClassification(
            mode=DOCUMENT_QA_MODE,
            reason="The prompt explicitly refers to an uploaded document or file.",
            confidence=0.9,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=True,
            needs_approval_review=False,
            artifact_type=None,
        )

    if artifact_type is not None:
        return TurnClassification(
            mode=RESEARCH_THEN_EXECUTION_MODE,
            reason="The prompt requests an artifact, which usually needs research or content gathering before generation.",
            confidence=0.93,
            needs_research=True,
            needs_execution=True,
            needs_document_analysis=has_uploaded_files,
            needs_approval_review=True,
            artifact_type=artifact_type,
        )

    if _is_execution_request(cleaned_prompt):
        return TurnClassification(
            mode=EXECUTION_MODE,
            reason="The prompt asks for a toolable or directly executable action.",
            confidence=0.92,
            needs_research=False,
            needs_execution=True,
            needs_document_analysis=False,
            needs_approval_review=_needs_approval_review(cleaned_prompt),
            artifact_type=None,
        )

    if _is_general_chat(cleaned_prompt):
        return TurnClassification(
            mode=GENERAL_CHAT_MODE,
            reason="The prompt is casual conversation or asks about the assistant itself.",
            confidence=0.97,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    if has_uploaded_files and _looks_like_information_request(cleaned_prompt):
        return TurnClassification(
            mode=DOCUMENT_QA_MODE,
            reason="Uploaded files are present and the prompt looks like an information request, so document-first analysis should run.",
            confidence=0.76,
            needs_research=False,
            needs_execution=False,
            needs_document_analysis=True,
            needs_approval_review=False,
            artifact_type=None,
        )

    if _is_research_request(cleaned_prompt):
        return TurnClassification(
            mode=WEB_RESEARCH_MODE,
            reason="The prompt appears to require external or current information gathering.",
            confidence=0.88,
            needs_research=True,
            needs_execution=False,
            needs_document_analysis=False,
            needs_approval_review=False,
            artifact_type=None,
        )

    # Low confidence on purpose: nothing matched a precise rule. The hybrid
    # intent router treats this as "ambiguous" and escalates to an LLM (or a
    # safe execution fallback) instead of trusting a keyword guess.
    return TurnClassification(
        mode=GENERAL_CHAT_MODE,
        reason="Defaulted to general chat because the prompt did not strongly match execution, research, or document-driven intent.",
        confidence=0.5,
        needs_research=False,
        needs_execution=False,
        needs_document_analysis=False,
        needs_approval_review=False,
        artifact_type=None,
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_general_chat(text: str) -> bool:
    return _starts_with_greeting(text) or _contains_any(text, _IDENTITY_PATTERNS)


def _starts_with_greeting(text: str) -> bool:
    stripped = text.strip()
    for greeting in _GENERAL_CHAT_PATTERNS:
        # Anchor at the start with a trailing word boundary so "hi" matches
        # "hi there" but not "hide the file", and greetings buried inside a
        # code string or longer instruction do not trigger chat mode.
        if re.match(rf"{re.escape(greeting)}\b", stripped):
            return True
    return False


def _is_self_memory_question(text: str) -> bool:
    return _contains_any(text, _SELF_MEMORY_PATTERNS)


def _has_explicit_document_reference(
    text: str,
    uploaded_file_names: Sequence[str] | None,
) -> bool:
    if _contains_any(text, _DOCUMENT_REFERENCE_PATTERNS):
        return True

    if uploaded_file_names:
        normalized_names = [_normalize_text(name) for name in uploaded_file_names]
        if any(name and name in text for name in normalized_names):
            return True

    return False


def _detect_artifact_type(text: str) -> str | None:
    for artifact_type, patterns in _ARTIFACT_PATTERNS.items():
        if _contains_any(text, patterns):
            return artifact_type
    return None


def _is_execution_request(text: str) -> bool:
    return _contains_any(text, _EXECUTION_PATTERNS)


def _is_research_request(text: str) -> bool:
    return _contains_any(text, _RESEARCH_PATTERNS)


def _looks_like_information_request(text: str) -> bool:
    if "?" in text:
        return True
    return _contains_any(text, _INFORMATION_REQUEST_PATTERNS)


def _needs_approval_review(text: str) -> bool:
    return _contains_any(text, _HIGH_RISK_EXECUTION_PATTERNS)