# File: backend/app/llm_answer_service.py
"""
Direct-answer service for AIRA-X.

The dedicated path for conversational and knowledge turns — greetings,
identity/capability questions, explanations, and self-memory questions. These
turns answer through the real LLM provider (Groq/OpenAI/Gemini via LLMClient),
never through the execution workflow, and never expose internal machinery.

The supervisor stays the single orchestrator: it routes the turn, then calls
this service for GENERAL_CHAT and SELF_MEMORY modes (non-streaming and
streaming). Provider choice stays behind LLMClient, so improving the model
later never touches the supervisor.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from app.conversation import (
    AIRA_X_PERSONA_SYSTEM_PROMPT,
    _MAX_HISTORY_CHARS_PER_MESSAGE,
    _MAX_HISTORY_TURNS,
    _build_history_prompt,
    generate_conversational_answer,
    offline_general_chat_message,
)
from app.core.llm import LLMClient
from app.turn_classifier import SELF_MEMORY_MODE

# Self-memory turns ("do you know me", "who am I") must be honest: recall only
# what THIS conversation contains, never invent personal details, and never
# sound evasive or robotic about it.
SELF_MEMORY_SYSTEM_PROMPT = (
    "You are AIRA-X, a warm and genuinely helpful AI assistant. The user is "
    "asking what you know or remember about THEM.\n\n"
    "Rules:\n"
    "- Your only memory of the user is the current conversation shown to you. "
    "If it contains personal details they shared (name, work, projects, "
    "preferences, earlier questions), recall them naturally and specifically.\n"
    "- If the conversation contains nothing personal, say so warmly in one or "
    "two sentences — you don't retain personal details and only know what's "
    "been shared in this conversation — and invite them to tell you about "
    "themselves or what they're working on.\n"
    "- NEVER invent names, facts, or history about the user.\n"
    "- No headings, no disclaimers about being an AI model, no policy talk. "
    "Keep it short, human, and friendly."
)


def offline_self_memory_message(history: Sequence[dict] | None = None) -> str:
    """Honest fallback when no LLM provider is available."""
    if history and any((m.get("content") or "").strip() for m in history):
        return (
            "I only know what you've shared in this conversation so far — I "
            "don't keep personal details beyond it. Happy to recap what we've "
            "discussed, or you can tell me more about yourself."
        )
    return (
        "I don't know anything about you yet — I only remember what's shared "
        "within our conversation. Tell me a bit about yourself or what you're "
        "working on, and I'll keep it in mind while we talk."
    )


class DirectAnswerService:
    """Real conversational / knowledge / self-memory answers."""

    def answer(
        self,
        goal: str,
        *,
        mode: str,
        history: Sequence[dict] | None = None,
    ) -> str:
        """Non-streaming direct answer for one turn."""
        if mode == SELF_MEMORY_MODE:
            return self._self_memory_answer(goal, history)
        # General chat / knowledge: the shared persona path (history-gated,
        # format-aware, memory-silent). Falls back offline internally.
        return generate_conversational_answer(goal, history)

    def stream(
        self,
        goal: str,
        *,
        mode: str,
        history: Sequence[dict] | None = None,
    ) -> Iterator[str]:
        """Token stream for one direct-answer turn."""
        system, prompt, temperature = self._prompt_for(goal, mode, history)
        for piece in LLMClient().stream(system, prompt, temperature=temperature):
            if piece:
                yield piece

    def fallback(self, goal: str, *, mode: str, history: Sequence[dict] | None = None) -> str:
        """Offline message when the provider yields nothing."""
        if mode == SELF_MEMORY_MODE:
            return offline_self_memory_message(history)
        return offline_general_chat_message(goal)

    # ── internals ────────────────────────────────────────────────────────────

    def _prompt_for(
        self, goal: str, mode: str, history: Sequence[dict] | None
    ) -> tuple[str, str, float]:
        if mode == SELF_MEMORY_MODE:
            return (
                SELF_MEMORY_SYSTEM_PROMPT,
                _memory_transcript_prompt(goal, history),
                0.4,
            )
        return (
            AIRA_X_PERSONA_SYSTEM_PROMPT,
            _build_history_prompt(goal, history),
            0.7,
        )

    def _self_memory_answer(self, goal: str, history: Sequence[dict] | None) -> str:
        try:
            answer = LLMClient().generate(
                system=SELF_MEMORY_SYSTEM_PROMPT,
                prompt=_memory_transcript_prompt(goal, history),
                temperature=0.4,
            )
        except Exception:
            answer = ""
        return (answer or "").strip() or offline_self_memory_message(history)


def _memory_transcript_prompt(goal: str, history: Sequence[dict] | None) -> str:
    """Self-memory prompts always carry the conversation, ungated.

    The general-chat memory gate drops history for new-topic turns — correct
    for chat, wrong for "who am I": these questions are ABOUT the conversation,
    so the transcript is the answer's only legitimate source.
    """
    if not history:
        return goal

    lines: list[str] = []
    for message in list(history)[-_MAX_HISTORY_TURNS:]:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        if len(content) > _MAX_HISTORY_CHARS_PER_MESSAGE:
            content = content[:_MAX_HISTORY_CHARS_PER_MESSAGE].rstrip() + "..."
        speaker = "User" if message.get("role") == "user" else "AIRA-X"
        lines.append(f"{speaker}: {content}")

    if not lines:
        return goal

    transcript = "\n".join(lines)
    return (
        "Our conversation so far (your ONLY memory of this user):\n"
        f"{transcript}\n\n"
        f"User: {goal}\n\n"
        "Answer as AIRA-X."
    )
