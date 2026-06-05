# File: backend/app/conversation.py
"""
Shared conversational-answer helper for AIRA-X.

Both the `/aira-x/run` route and the `/assistant/run` route use this so that
greetings and casual / everyday questions get the same warm, natural, concise
replies instead of encyclopedic, headed, essay-style output.
"""

from __future__ import annotations

from app.core.llm import LLMClient

AIRA_X_PERSONA_SYSTEM_PROMPT = (
    "You are AIRA-X, a warm, friendly, and genuinely helpful AI assistant. "
    "Talk like a thoughtful human assistant in a chat — natural and personable.\n\n"
    "How to reply:\n"
    "- Match the user's tone and length. A short or casual message gets a short, "
    "friendly reply. Never answer a one-word greeting with an essay.\n"
    "- Write plain conversational prose. Do NOT add headings, titles, or labels "
    "such as 'Meaning of ...', 'Greeting Response', or section headers. Just talk.\n"
    "- For greetings in any language (e.g. hello, hola, aloha, namaste, bonjour), "
    "greet back warmly in a sentence or two and invite the user to share what they "
    "need. A single tasteful emoji is welcome, but optional.\n"
    "- Do not define or explain a word unless the user explicitly asks what it means.\n"
    "- Never invent facts, names, or organizations. If you are unsure, say so briefly.\n"
    "- When asked who you are or what you can do, introduce yourself as AIRA-X and "
    "briefly mention you can chat, research topics, analyze uploaded documents, run "
    "safe tasks, and create artifacts like slides, documents, and spreadsheets.\n"
    "Keep it concise, human, and helpful."
)


def offline_general_chat_message(goal: str) -> str:
    """Branded fallback used when no LLM provider is configured."""
    normalized_goal = goal.strip().lower()

    if "who are you" in normalized_goal:
        return (
            "I’m AIRA-X, an AI assistant that can help with research, document understanding, "
            "safe task execution, and artifact generation like presentations and reports."
        )
    if "what can you do" in normalized_goal or "how can you help" in normalized_goal:
        return (
            "I can answer questions, analyze uploaded documents, research topics, run safe execution "
            "workflows, and generate artifacts like PPTX, DOCX, and XLSX files when needed."
        )
    return (
        "Hi! I’m AIRA-X. I can help with general questions, research, document analysis, "
        "and execution-focused tasks. What would you like to do?"
    )


def generate_conversational_answer(goal: str) -> str:
    """Answer a general-chat / daily-life question, using the LLM when available."""
    answer = LLMClient().generate(
        system=AIRA_X_PERSONA_SYSTEM_PROMPT,
        prompt=goal,
        temperature=0.7,
    )

    cleaned = (answer or "").strip()

    # LLMClient returns a canned notice when no provider is configured or the
    # call fails; in that case fall back to the branded offline message.
    if (
        not cleaned
        or "no language model provider" in cleaned.lower()
        or "could not generate a response" in cleaned.lower()
    ):
        return offline_general_chat_message(goal)

    return cleaned
