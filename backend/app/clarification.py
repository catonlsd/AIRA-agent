# File: backend/app/clarification.py
"""
Guided clarification with real continuation (Phase 2A enhancement).

When the supervisor decides a request is genuinely under-specified, it can now
present *selectable options* instead of only open questions, remember the
pending request per session, parse the user's selection on the next turn
("1B, 2B, 3B", "use the second stack", or free-form custom text), and resume
the original task using the exact selected choices.

State is an in-memory per-session store: one pending clarification per session,
overwritten by newer ones and cleared on resolution. Best-effort by design —
if the server restarts, the user simply re-asks.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Optional

# ── Option templates ─────────────────────────────────────────────────────────

# Group key -> human label (used for continuation prompts and parsing hints).
_GROUP_LABELS = {1: "Stack", 2: "Tools", 3: "Output format"}
# Group key -> stable id used by the structured clarification payload / UI.
_GROUP_IDS = {1: "stack", 2: "tools", 3: "output_format"}
# Reverse lookup for parsing structured "Label: value" replies.
_LABEL_TO_GROUP = {
    "stack": 1,
    "tools": 2,
    "output format": 3,
    "output_format": 3,
}

# The guided template for RAG / retrieval build requests.
_RAG_OPTION_GROUPS: dict[int, dict[str, str]] = {
    1: {
        "A": "FastAPI + ChromaDB + Groq",
        "B": "Next.js + FastAPI + FAISS",
        "C": "LangChain + ChromaDB + OpenAI-compatible LLM",
        "D": "Custom stack",
    },
    2: {
        "A": "PDF upload + semantic search",
        "B": "Hybrid search + citations",
        "C": "Multi-document Q&A + memory",
        "D": "Custom tools",
    },
    3: {
        "A": "Step-by-step implementation plan",
        "B": "Backend implementation",
        "C": "Full backend + frontend structure",
        "D": "Custom format",
    },
}

# Ordinal words -> option letters, for "use the second stack".
_ORDINALS = {"first": "A", "second": "B", "third": "C", "fourth": "D"}

# Group keyword -> group number, for "option 2 for tools".
_GROUP_KEYWORDS = {
    "stack": 1,
    "framework": 1,
    "tech": 1,
    "tool": 2,
    "tools": 2,
    "feature": 2,
    "output": 3,
    "format": 3,
    "deliverable": 3,
}

_CODE_PATTERN = re.compile(r"\b([1-9])\s*[-.]?\s*([A-Da-d])\b")
_QUESTION_LEAD = re.compile(
    r"^\s*(what|who|when|where|why|how|is|are|do|does|can|could|should|would)\b"
)


@dataclass
class PendingClarification:
    """A clarification waiting for the user's answer, scoped to one session."""

    original_request: str
    questions: list[str] = field(default_factory=list)
    option_groups: dict[int, dict[str, str]] = field(default_factory=dict)
    status: str = "awaiting_clarification"

    @property
    def option_map(self) -> dict[str, str]:
        return {
            f"{group}{letter}": label
            for group, options in self.option_groups.items()
            for letter, label in options.items()
        }


@dataclass
class ClarificationSelection:
    """The parsed result of the user's clarification reply."""

    choices: dict[int, str] = field(default_factory=dict)  # group -> option text
    custom_notes: Optional[str] = None

    @property
    def selected_options(self) -> dict[str, str]:
        return {
            _GROUP_LABELS.get(group, f"Group {group}"): text
            for group, text in self.choices.items()
        }


class ClarificationStore:
    """In-memory pending-clarification state, one entry per session."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingClarification] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: Optional[str]) -> str:
        return session_id or "anonymous"

    def set(self, session_id: Optional[str], pending: PendingClarification) -> None:
        with self._lock:
            self._pending[self._key(session_id)] = pending

    def get(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        with self._lock:
            return self._pending.get(self._key(session_id))

    def clear(self, session_id: Optional[str]) -> None:
        with self._lock:
            self._pending.pop(self._key(session_id), None)


# Module-level store shared by the supervisor (process-local by design).
clarification_store = ClarificationStore()


# ── Resolved-task planning (clarification → plan → approval → execution) ─────


@dataclass
class PendingPlan:
    """A plan built from a resolved clarification, awaiting user approval."""

    original_request: str
    goal: str  # the reconstructed task (original request + exact selections)
    resolved_task: dict = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)
    status: str = "awaiting_approval"


# Same session-store mechanics, separate slot: a session can be waiting on a
# clarification answer OR a plan approval, never both.
plan_store = ClarificationStore()

_PLAN_APPROVE_PATTERN = re.compile(
    r"^\s*(approve(\s+(the\s+)?plan)?|yes[,.!]?(\s+(please|proceed|go ahead|do it))?|"
    r"proceed|go ahead|looks good|lgtm|start|run it|execute(\s+(the\s+)?plan)?|do it)\s*[.!]*\s*$",
    re.IGNORECASE,
)
_PLAN_REJECT_PATTERN = re.compile(
    r"^\s*(reject|cancel|no[,.!]?(\s+thanks)?|stop|discard|forget it|never\s?mind|don'?t)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def parse_plan_decision(reply: str) -> Optional[str]:
    """Classify a reply against a pending plan: "approve", "reject", or None."""
    text = (reply or "").strip()
    if not text:
        return None
    if _PLAN_APPROVE_PATTERN.match(text):
        return "approve"
    if _PLAN_REJECT_PATTERN.match(text):
        return "reject"
    return None


def resolved_task_from(
    pending: PendingClarification, selection: ClarificationSelection
) -> dict:
    """The structured record of what was asked and what was chosen."""
    return {
        "original_request": pending.original_request,
        "selected_stack": selection.choices.get(1),
        "selected_tools": selection.choices.get(2),
        "selected_output_format": selection.choices.get(3),
        "custom_notes": selection.custom_notes,
    }


def generate_plan_steps(
    original_request: str, selection: ClarificationSelection
) -> list[str]:
    """Concrete execution-plan steps derived from the exact selections.

    Stack fidelity matters: the chosen components are named in the steps so the
    later execution cannot silently substitute technologies.
    """
    stack = selection.choices.get(1)
    tools = selection.choices.get(2)
    output_format = (selection.choices.get(3) or "").lower()

    steps = ["Inspect the project structure and confirm conventions"]
    if stack:
        steps.append(f"Scaffold the core services using {stack}")
    if tools:
        steps.append(f"Implement {tools}")

    wants_backend = "backend" in output_format or "frontend" in output_format
    if "backend" in output_format and "frontend" in output_format:
        steps.append("Create/update backend service files")
        steps.append("Create/update frontend pages and components")
    elif wants_backend:
        steps.append("Create/update backend implementation files")

    if selection.custom_notes:
        steps.append(f"Apply custom preferences: {selection.custom_notes}")

    steps.append("Add required dependencies and configuration")
    steps.append("Validate with tests or a build check")
    return steps


def render_plan_message(
    selection: ClarificationSelection, steps: list[str]
) -> str:
    """The plan-ready reply: acknowledgment, numbered plan, approval gate."""
    ack = acknowledgment_for(selection)
    numbered = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))
    intro = f"{ack}\n\n" if ack else ""
    return (
        f"{intro}Plan:\n{numbered}\n\n"
        "Approval required before modifying project files. "
        'Reply "approve plan" to proceed, or tell me what to change.'
    )


# ── Option generation + rendering ────────────────────────────────────────────


def option_groups_for(message: str) -> dict[int, dict[str, str]]:
    """Return guided option groups for the request, or {} for plain questions."""
    text = message.lower()
    if re.search(r"\brag\b|retrieval[- ]augmented|semantic search engine", text):
        return {group: dict(options) for group, options in _RAG_OPTION_GROUPS.items()}
    return {}


def render_clarification_message(pending: PendingClarification) -> str:
    """Render the user-facing clarification reply (options or plain questions)."""
    if not pending.option_groups:
        bullets = "\n".join(f"- {question}" for question in pending.questions)
        return (
            "Happy to help — a couple of quick details first so I get it right:\n"
            f"{bullets}"
        )

    blocks: list[str] = []
    for group in sorted(pending.option_groups):
        label = _GROUP_LABELS.get(group, f"Choice {group}")
        lines = [f"{group}. {label}"]
        for letter in sorted(pending.option_groups[group]):
            lines.append(f"   {letter}. {pending.option_groups[group][letter]}")
        blocks.append("\n".join(lines))

    options_text = "\n\n".join(blocks)
    return (
        "Happy to help — choose the setup so I build the right thing:\n\n"
        f"{options_text}\n\n"
        "Reply like: 1B, 2B, 3B — or write your custom preference."
    )


def structured_clarification(pending: PendingClarification) -> Optional[dict]:
    """The machine-readable clarification payload for interactive UIs.

    Returned alongside the readable text so older clients keep working; the
    frontend prefers this shape and renders clickable option cards.
    """
    if not pending.option_groups:
        return None

    questions = []
    for group in sorted(pending.option_groups):
        group_id = _GROUP_IDS.get(group, f"group_{group}")
        options = []
        for letter in sorted(pending.option_groups[group]):
            label = pending.option_groups[group][letter]
            is_custom = "custom" in label.lower()
            options.append(
                {
                    "id": f"{group_id}_{'custom' if is_custom else letter.lower()}",
                    "label": label,
                    "value": "custom" if is_custom else label,
                }
            )
        questions.append(
            {
                "id": group_id,
                "title": _GROUP_LABELS.get(group, f"Choice {group}"),
                "required": True,
                "options": options,
            }
        )

    return {
        "required": True,
        "original_request": pending.original_request,
        "questions": questions,
    }


# ── Selection parsing ────────────────────────────────────────────────────────


def _parse_structured_reply(text: str) -> Optional[ClarificationSelection]:
    """Parse the structured "Clarification response:" payload sent by the UI.

    Values are used verbatim, so custom answers flow through unchanged.
    """
    selection = ClarificationSelection()
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        key = label.strip().lower()
        value = value.strip()
        if not value or key == "original request":
            continue
        group = _LABEL_TO_GROUP.get(key)
        if group is not None:
            selection.choices[group] = value
        elif key in ("custom", "notes", "custom notes", "additional preferences"):
            selection.custom_notes = value
    if selection.choices or selection.custom_notes:
        return selection
    return None


def parse_selection(
    reply: str, pending: PendingClarification
) -> Optional[ClarificationSelection]:
    """Parse the user's reply against the pending clarification.

    Returns None when the reply does not look like an answer (e.g. an unrelated
    question), so the supervisor routes it normally and keeps the state.
    """
    text = (reply or "").strip()
    if not text:
        return None

    lowered = text.lower()

    # The interactive option-card UI sends a structured reply — parse it first.
    if lowered.startswith("clarification response"):
        return _parse_structured_reply(text)

    selection = ClarificationSelection()

    # 1. Explicit codes: "1B", "1b, 2c", "option 1B and 2C".
    for group_str, letter in _CODE_PATTERN.findall(text):
        group = int(group_str)
        option = pending.option_groups.get(group, {}).get(letter.upper())
        if option:
            selection.choices[group] = option

    # 2. Ordinals with a group keyword: "use the second stack".
    if pending.option_groups:
        for ordinal, letter in _ORDINALS.items():
            if ordinal not in lowered:
                continue
            for keyword, group in _GROUP_KEYWORDS.items():
                if keyword in lowered:
                    option = pending.option_groups.get(group, {}).get(letter)
                    if option:
                        selection.choices.setdefault(group, option)

    # 3. Free-text mentions of option content: "Use Next.js + FastAPI + FAISS".
    answer_prefixed = lowered.startswith(
        ("use ", "custom", "option", "go with", "pick", "choose", "i want", "let's")
    )
    looks_like_answer = bool(selection.choices) or answer_prefixed
    if pending.option_groups and looks_like_answer:
        for group, options in pending.option_groups.items():
            if group in selection.choices:
                continue
            best, best_hits = None, 0
            for label in options.values():
                tokens = [t for t in re.split(r"[^a-z0-9.]+", label.lower()) if len(t) > 2]
                hits = sum(1 for t in tokens if t in lowered)
                if hits > best_hits:
                    best, best_hits = label, hits
            if best and best_hits >= 1 and "custom" not in best.lower():
                selection.choices[group] = best

    # Unrelated messages (questions, fresh commands) must not be swallowed as
    # answers: only answer-shaped replies become a custom preference.
    if not selection.choices:
        if _QUESTION_LEAD.match(lowered) or lowered.endswith("?"):
            return None
        if not answer_prefixed:
            return None
        selection.custom_notes = text
        return selection

    # Capture trailing custom text alongside codes ("1B, custom: use Qdrant").
    custom_match = re.search(r"custom\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if custom_match and custom_match.group(1).strip():
        selection.custom_notes = custom_match.group(1).strip()

    # "Custom" picks fall back to the user's own words.
    for group, chosen in list(selection.choices.items()):
        if "custom" in chosen.lower() and selection.custom_notes:
            selection.choices[group] = selection.custom_notes

    return selection


# ── Continuation ─────────────────────────────────────────────────────────────


def build_continuation_goal(
    pending: PendingClarification, selection: ClarificationSelection
) -> str:
    """Combine the original request with the selected choices for re-dispatch."""
    lines = [f"Original request: {pending.original_request}", "", "User selected:"]
    for group in sorted(selection.choices):
        label = _GROUP_LABELS.get(group, f"Choice {group}")
        lines.append(f"- {label}: {selection.choices[group]}")
    if selection.custom_notes:
        lines.append(f"- Additional preferences: {selection.custom_notes}")
    lines.append("")
    lines.append(
        "Proceed with the original task using these exact choices. Do not ask "
        "for clarification again, and do not substitute different technologies."
    )
    return "\n".join(lines)


def acknowledgment_for(selection: ClarificationSelection) -> str:
    """One-line confirmation of what was chosen, prefixed to the answer."""
    parts = [text for _, text in sorted(selection.choices.items())]
    if not parts and selection.custom_notes:
        parts = [selection.custom_notes]
    if not parts:
        return ""
    joined = "; ".join(parts)
    return f"Great — proceeding with: {joined}."
