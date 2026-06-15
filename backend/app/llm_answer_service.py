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

from typing import Iterator, Mapping, Sequence

from app.conversation import (
    AIRA_X_PERSONA_SYSTEM_PROMPT,
    _MAX_HISTORY_CHARS_PER_MESSAGE,
    _MAX_HISTORY_TURNS,
    _build_history_prompt,
    generate_conversational_answer,
    offline_general_chat_message,
)
from app.memory.preference_policy import (
    build_style_directive,
    summarize_for_self_memory,
)
from app.core.llm import LLMClient
from app.product_manifest import (
    is_product_meta_question,
    manifest_context,
    offline_meta_answer,
)
from app.turn_classifier import SELF_MEMORY_MODE

# Self/meta questions ("what can you do", "what additions does your
# architecture need") answer from the product manifest — never from generic
# chatbot knowledge. Style is enforced: grounded, concise, zero boilerplate.
PRODUCT_META_SYSTEM_PROMPT = (
    "You are AIRA-X, answering a question about YOURSELF — your identity, "
    "capabilities, limitations, or what should be improved in your "
    "architecture.\n\n"
    "Ground every claim in the product truth below. Reference real system "
    "areas (supervisor, execution loop, runtime validation, repair loop, "
    "ChromaDB document retrieval, tracing, artifact pipeline, frontend UX) — "
    "never invent features.\n\n"
    "STYLE RULES (strict):\n"
    "- Start directly with the substance. No gratitude, no praise, no "
    "'thank you for asking'.\n"
    "- NEVER use generic AI phrases such as 'advanced NLP', 'knowledge "
    "graphs', 'improved contextual understanding', or 'as an AI language "
    "model'.\n"
    "- Be concise, strategic, and specific — like a strong engineer "
    "describing their own system. Short paragraphs or tight bullets.\n"
    "- Honest about limitations; no marketing fluff.\n\n"
    "PRODUCT TRUTH:\n"
)

# Self-memory turns ("do you know me", "who am I") must be honest: recall only
# what THIS conversation contains, never invent personal details, and never
# sound evasive or robotic about it.
SELF_MEMORY_SYSTEM_PROMPT = (
    "You are AIRA-X, a warm and genuinely helpful AI assistant. The user is "
    "asking what you know or remember about THEM.\n\n"
    "Rules:\n"
    "- Your memory has two parts, both shown to you below: (a) THIS "
    "conversation, and (b) any SAVED PREFERENCES the user explicitly asked you "
    "to keep. Recall both honestly and specifically.\n"
    "- Distinguish them naturally: stable saved preferences vs. things just "
    "mentioned in this conversation.\n"
    "- If there are saved preferences, state them plainly (e.g. 'You've asked "
    "me to keep answers concise'). Do not over-personalise beyond them.\n"
    "- If the user asks to change or forget preferences, tell them they're in "
    "control: saved preferences can be reviewed, edited, or cleared anytime in "
    "Settings, and they can also just tell you a new preference here.\n"
    "- If there are NO saved preferences and nothing personal in the "
    "conversation, say so warmly in one or two sentences — you don't retain "
    "personal details, only what's been shared or saved as a preference — and "
    "invite them to tell you what they're working on.\n"
    "- NEVER invent names, facts, history, or preferences. Only state what is "
    "actually shown below.\n"
    "- No headings, no disclaimers about being an AI model, no policy talk. "
    "Keep it short, human, and friendly."
)


def offline_self_memory_message(
    history: Sequence[dict] | None = None,
    preferences: Mapping[str, str] | None = None,
) -> str:
    """Honest fallback when no LLM provider is available."""
    saved = summarize_for_self_memory(dict(preferences or {}))
    if saved:
        return (
            f"{saved} Beyond that, I only know what's been shared in this "
            "conversation — I don't keep other personal details."
        )
    if history and any((m.get("content") or "").strip() for m in history):
        return (
            "I only know what you've shared in this conversation so far — I "
            "don't keep personal details beyond it, and you haven't saved any "
            "preferences yet. Happy to recap what we've discussed."
        )
    return (
        "I don't know anything about you yet — I only remember what's shared "
        "within our conversation, plus any preferences you ask me to keep. "
        "Tell me what you're working on and I'll keep it in mind while we talk."
    )


class DirectAnswerService:
    """Real conversational / knowledge / self-memory answers."""

    def answer(
        self,
        goal: str,
        *,
        mode: str,
        history: Sequence[dict] | None = None,
        preferences: Mapping[str, str] | None = None,
    ) -> str:
        """Non-streaming direct answer for one turn."""
        if mode == SELF_MEMORY_MODE:
            return self._self_memory_answer(goal, history, preferences)
        # Product-self questions answer from the manifest, never generically.
        if is_product_meta_question(goal):
            return self._meta_answer(goal)
        # General chat / knowledge: the shared persona path (history-gated,
        # format-aware, memory-silent). Saved style preferences apply as defaults.
        return generate_conversational_answer(goal, history, preferences=preferences)

    def stream(
        self,
        goal: str,
        *,
        mode: str,
        history: Sequence[dict] | None = None,
        preferences: Mapping[str, str] | None = None,
    ) -> Iterator[str]:
        """Token stream for one direct-answer turn."""
        system, prompt, temperature = self._prompt_for(goal, mode, history, preferences)
        for piece in LLMClient().stream(system, prompt, temperature=temperature):
            if piece:
                yield piece

    def fallback(
        self,
        goal: str,
        *,
        mode: str,
        history: Sequence[dict] | None = None,
        preferences: Mapping[str, str] | None = None,
    ) -> str:
        """Offline message when the provider yields nothing."""
        if mode == SELF_MEMORY_MODE:
            return offline_self_memory_message(history, preferences)
        if is_product_meta_question(goal):
            return offline_meta_answer(goal)
        return offline_general_chat_message(goal)

    # ── internals ────────────────────────────────────────────────────────────

    def _prompt_for(
        self,
        goal: str,
        mode: str,
        history: Sequence[dict] | None,
        preferences: Mapping[str, str] | None = None,
    ) -> tuple[str, str, float]:
        if mode == SELF_MEMORY_MODE:
            return (
                SELF_MEMORY_SYSTEM_PROMPT,
                _memory_transcript_prompt(goal, history, preferences),
                0.4,
            )
        if is_product_meta_question(goal):
            return (
                PRODUCT_META_SYSTEM_PROMPT + manifest_context(),
                goal,
                0.3,
            )
        # Saved style preferences are appended as defaults; the directive itself
        # states the current message overrides them (the current turn wins).
        return (
            AIRA_X_PERSONA_SYSTEM_PROMPT + build_style_directive(dict(preferences or {})),
            _build_history_prompt(goal, history),
            0.7,
        )

    def _meta_answer(self, goal: str) -> str:
        try:
            answer = LLMClient().generate(
                system=PRODUCT_META_SYSTEM_PROMPT + manifest_context(),
                prompt=goal,
                temperature=0.3,
            )
        except Exception:
            answer = ""
        return (answer or "").strip() or offline_meta_answer(goal)

    def _self_memory_answer(
        self,
        goal: str,
        history: Sequence[dict] | None,
        preferences: Mapping[str, str] | None = None,
    ) -> str:
        try:
            answer = LLMClient().generate(
                system=SELF_MEMORY_SYSTEM_PROMPT,
                prompt=_memory_transcript_prompt(goal, history, preferences),
                temperature=0.4,
            )
        except Exception:
            answer = ""
        return (answer or "").strip() or offline_self_memory_message(history, preferences)


def _memory_transcript_prompt(
    goal: str,
    history: Sequence[dict] | None,
    preferences: Mapping[str, str] | None = None,
) -> str:
    """Self-memory prompts carry the conversation AND any saved preferences.

    The general-chat memory gate drops history for new-topic turns — correct
    for chat, wrong for "who am I": these questions are ABOUT the user's context,
    so the transcript and saved preferences are the answer's only legitimate
    sources. Personal facts are never invented (the system prompt forbids it).
    """
    saved = summarize_for_self_memory(dict(preferences or {}))
    saved_block = f"Saved preferences (stable, the user asked you to keep these): {saved}\n\n" if saved else ""

    if not history:
        if saved_block:
            return (
                f"{saved_block}There is no other conversation context yet.\n\n"
                f"User: {goal}\n\nAnswer as AIRA-X."
            )
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
        if saved_block:
            return (
                f"{saved_block}There is no other conversation context yet.\n\n"
                f"User: {goal}\n\nAnswer as AIRA-X."
            )
        return goal

    transcript = "\n".join(lines)
    return (
        f"{saved_block}"
        "Our conversation so far (your memory of this user, alongside any saved "
        "preferences above):\n"
        f"{transcript}\n\n"
        f"User: {goal}\n\n"
        "Answer as AIRA-X."
    )
