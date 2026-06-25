# File: backend/app/conversation.py
"""
Shared conversational-answer helper for AIRA-X.

Both the `/aira-x/run` route and the `/assistant/run` route use this so that
greetings and casual / everyday questions get the same warm, natural, concise
replies instead of encyclopedic, headed, essay-style output.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from app.core.llm import LLMClient

# How much recent conversation to feed back to the model, and how much of each
# message to keep, so the prompt stays bounded. The per-message cap is generous
# enough that a follow-up like "put that in bullet points" still sees the full
# previous answer instead of a truncated fragment.
_MAX_HISTORY_TURNS = 6
_MAX_HISTORY_CHARS_PER_MESSAGE = 2000

AIRA_X_PERSONA_SYSTEM_PROMPT = (
    "You are AIRA-X, a warm, friendly, and genuinely helpful AI assistant. "
    "Talk like a thoughtful human assistant in a chat — natural, clear, and "
    "personable.\n\n"
    "How to reply:\n"
    "- Match the user's tone and length. A short or casual message gets a short, "
    "friendly reply. Never answer a one-word greeting with an essay.\n"
    "- Do not add headings, titles, or section labels to short, casual replies, "
    "and never invent robotic labels such as 'Meaning of ...' or 'Greeting "
    "Response'. Just talk.\n"
    "- For greetings in any language (e.g. hello, hola, aloha, namaste, bonjour), "
    "greet back warmly in a sentence or two and invite the user to share what they "
    "need.\n"
    "- Use emojis very sparingly, only when they genuinely add warmth. Do NOT end "
    "your replies with an emoji out of habit, and do not tack an emoji onto the "
    "closing line of an answer. Most answers should contain no emoji at all.\n"
    "- Do not define or explain a word unless the user explicitly asks what it means.\n"
    "- Never invent facts, names, dates, or organizations. If you are unsure, say so "
    "briefly.\n\n"
    "Formatting — be smart about structure:\n"
    "- When the user asks for a specific format (bullet points, a numbered list, a "
    "table, steps, a short summary, etc.), follow that request EXACTLY using clean "
    "Markdown.\n"
    "- Put each list item on its OWN line, starting with '- ' for bullets or '1.' "
    "for a numbered list. Never cram multiple items into one running paragraph.\n"
    "- Even when not explicitly asked, use light Markdown (short paragraphs, '- ' "
    "bullets, **bold** for key terms) whenever it makes a multi-item or "
    "step-by-step answer easier to read — for example a list of people, options, "
    "dates, or instructions.\n"
    "- If the user asks you to reformat, restructure, or shorten your previous "
    "answer, rewrite that same content in the requested format. Keep every item — "
    "do not silently drop entries or start an unrelated answer.\n\n"
    "Memory — use it silently:\n"
    "- Use the recent conversation only to understand the current question. Do NOT "
    "mention, restate, or refer back to earlier topics unless the user explicitly "
    "asks about them or that context is genuinely needed to answer correctly.\n"
    "- If the user switches to a new subject, just answer the new question "
    "directly. Never narrate the switch — avoid phrases like 'since we were "
    "discussing ...', 'going back to ...', 'as we talked about', or 'as mentioned "
    "earlier'. Memory should improve the answer, never become part of it.\n\n"
    "When asked who you are or what you can do, introduce yourself as AIRA-X — an "
    "AI assistant that researches topics with cited sources, understands uploaded "
    "documents, runs approval-gated execution workflows, and generates artifacts "
    "like slides, documents, spreadsheets, and code projects. Keep the pitch to a "
    "few warm sentences — no feature dumps.\n"
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


# ── Turn classification (continuation / follow-up / explicit recall / new topic)
# Used to decide whether prior conversation should inform the reply. A genuinely
# new topic gets NO prior context, so the model cannot leak or narrate it.

# The user is explicitly asking about the prior conversation.
_EXPLICIT_RECALL_PATTERNS = (
    r"\bwhat did (you|we|i)\b",
    r"\b(you|we) (just )?(said|mentioned|told|asked|wrote|discussed|talked)\b",
    r"\b(earlier|previously|before|a moment ago|just now)\b",
    r"\b(last|previous) (answer|message|reply|response|question|point|thing)\b",
    r"\b(repeat|rephrase that|say that again|recap|remind me)\b",
    r"\bwhat (have|were) we (been )?(discuss|talk)",
    r"\bour (conversation|chat|discussion)\b",
    r"\bwhat emoji\b",
)

# The user wants the previous answer continued / reformatted / expanded.
_CONTINUATION_PATTERNS = (
    r"^\s*(continue|go on|keep going|proceed|next|more|and)\s*[.?!]*\s*$",
    r"\b(tell me more|go deeper|elaborate|expand on (that|this|it)|more detail)\b",
    r"\b(in|as) (bullet|numbered)\b",
    r"\bas a (list|table|summary)\b",
    r"\b(make|keep) (it|that|this) (short|brief|long|simpl|detail|concise)",
    r"\b(reformat|restructure|rewrite|reword|rephrase|shorten|summari[sz]e) "
    r"(it|that|this|the (previous|last|above))\b",
    r"\b(explain|break down) (that|this|it)\b",
)

# Anaphoric / connector-led follow-ups that lean on the previous turn.
_FOLLOWUP_LEAD = re.compile(r"^\s*(and|but|so|also|then|or|what about|how about)\b")
_ANAPHORA = re.compile(r"\b(it|its|that|this|they|them|those|these|their|he|she)\b")
_SHORT_QUESTION_LEAD = re.compile(r"^\s*(why|how|really|seriously|when|where|who)\b")


def classify_memory_use(goal: str, history: Sequence[dict] | None = None) -> str:
    """Classify the current turn relative to the conversation so far.

    Returns one of: ``"explicit_recall"``, ``"continuation"``, ``"follow_up"``,
    or ``"new_topic"``. With no prior history every turn is a new topic.
    """
    text = (goal or "").strip().lower()
    if not text or not history:
        return "new_topic"

    for pattern in _EXPLICIT_RECALL_PATTERNS:
        if re.search(pattern, text):
            return "explicit_recall"
    for pattern in _CONTINUATION_PATTERNS:
        if re.search(pattern, text):
            return "continuation"

    if _FOLLOWUP_LEAD.match(text):
        return "follow_up"

    words = re.findall(r"\w+", text)
    # A short question that leans on an unstated subject (anaphora) is a follow-up;
    # a self-contained question with its own subject is a new topic.
    if len(words) <= 6 and _ANAPHORA.search(text):
        return "follow_up"
    # Only a bare interjection-question ("why?", "really?") leans on the prior
    # turn; a short question with its own subject ("Who invented Linux?") is new.
    if len(words) <= 2 and _SHORT_QUESTION_LEAD.match(text):
        return "follow_up"

    return "new_topic"


def _build_history_prompt(goal: str, history: Sequence[dict] | None) -> str:
    """Prepend recent conversation turns so replies are context-aware.

    A genuinely new topic is answered fresh with no prior context attached, so the
    model cannot reference or narrate earlier topics. Continuations, follow-ups,
    and explicit recall keep the transcript (used silently, per the persona).
    """
    if not history:
        return goal

    if classify_memory_use(goal, history) == "new_topic":
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
        "Here is our recent conversation, for context only. Use it silently to "
        "understand the question — do not mention or refer back to earlier topics "
        "unless the user explicitly asks.\n"
        f"{transcript}\n\n"
        f"User: {goal}\n\n"
        "Reply as AIRA-X."
    )


def generate_conversational_answer(
    goal: str,
    history: Sequence[dict] | None = None,
    *,
    preferences: Mapping[str, str] | None = None,
) -> str:
    """Answer a general-chat / daily-life question, using the LLM when available.

    When ``history`` (recent {role, content} turns) is provided, it is included
    so the reply stays aware of what was just discussed. Saved style preferences
    are appended to the system prompt as defaults (the current message overrides
    them — the directive says so explicitly).
    """
    from app.memory.preference_policy import build_style_directive

    answer = LLMClient().generate(
        system=AIRA_X_PERSONA_SYSTEM_PROMPT + build_style_directive(dict(preferences or {})),
        prompt=_build_history_prompt(goal, history),
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
