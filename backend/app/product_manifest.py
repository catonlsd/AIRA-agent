# File: backend/app/product_manifest.py
"""
The AIRA-X product manifest — the single truth source for self-description.

When users ask AIRA-X about itself (identity, capabilities, limitations,
architecture needs, what to build next), answers must be grounded in THIS
product — its supervisor, execution loop, ChromaDB retrieval, tracing — never
in generic chatbot language ("advanced NLP", "knowledge graphs").

Maintained by hand, deliberately: when the product changes, this file is the
one place self-knowledge updates.
"""

from __future__ import annotations

import re

MANIFEST: dict = {
    "identity": (
        "AIRA-X is an AI assistant platform built around one supervisor brain: "
        "every turn is classified and routed to the right capability — "
        "conversation, web research, document Q&A, or approval-gated execution."
    ),
    "capabilities": [
        "Routed intelligence: a hybrid keyword+LLM intent router with a reasoning layer (conversation typing, route confidence, capability composition)",
        "Document-first answers: uploaded files are chunked and embedded into ChromaDB, answered with citations and honest 'not in your files' responses",
        "Web research with source-grounded answers",
        "Execution workflows: structured machine-readable plans, approval gates, real tool calls (files, shell, git, python) with evidence-based completion",
        "Runtime validation: generated projects are install/compile-checked with a bounded diagnose-and-repair loop",
        "Guided clarification: vague requests get selectable option cards, and the chosen options actually drive the resumed work",
        "Per-turn tracing: route, confidence, capabilities, stages, latency, evidence",
        "Token-streamed answers over SSE with a live supervisor status (Octa)",
    ],
    "limitations": [
        "Artifact generation (PPTX/DOCX/XLSX) is not yet wired through the evidence-based plan executor",
        "Runtime validation covers dependency install and compile smoke-tests, not booting long-running apps",
        "Pending approval/clarification state is in-memory per session and does not survive restarts",
        "Storage is single-node (SQLite + local ChromaDB); scaling needs Postgres and a hosted vector store",
        "Approvals gate the plan and the runtime batch, not yet each individual risky command",
    ],
    "architecture_needs": [
        "Wire artifact generation (PPTX/DOCX) through the plan executor so decks and documents come with file evidence, not prose",
        "Deepen runtime validation: boot the generated app and smoke-test real endpoints, not just compile checks",
        "Strengthen the repair loop with multi-attempt diagnostics that read tracebacks and patch the specific failing code",
        "Improve document grounding: hybrid (keyword + semantic) retrieval and reranking on top of ChromaDB",
        "Surface traces in the product: per-run timelines of route, tools, evidence, and repairs in the UI",
        "Add save-location approval so generated outputs land where the user chooses",
        "Persist pending plans/approvals so flows survive restarts",
        "Stand up CI so the regression wall runs on every change",
    ],
    "philosophy": (
        "Evidence over claims: execution is never reported complete without real "
        "proof (files written, commands run, validation passed). Risk is "
        "approval-gated. Memory improves answers without becoming part of them."
    ),
}

# Phrases that must never appear in self-description answers.
BANNED_PHRASES = (
    "advanced nlp",
    "knowledge graph",
    "improved contextual understanding",
    "as an ai language model",
    "thank you for the opportunity",
    "natural language processing capabilities",
)

_META_PATTERNS = (
    r"\bwho (are|made|created|built|designed) you\b",
    r"\bwhat (are|can) you do\b",
    r"\bwhat are you\b",
    r"\babout yourself\b",
    r"\byour (own )?(architecture|capabilit\w*|limitation\w*|roadmap|design|precision|weakness\w*|strength\w*|improvement\w*)\b",
    r"\bwhat (additions|changes|improvements) do you need\b",
    r"\bwhat do you need (to|in order to)\b",
    r"\bwhat should (be improved|we improve|i improve) in you\b",
    r"\bhow can you (be|become|get) (more )?(precise|accurate|reliable|better)\b",
    r"\bwhat should (we|i) build next in aira",
    r"\bimprove (you|yourself)\b",
)
_META_REGEX = re.compile("|".join(_META_PATTERNS), re.IGNORECASE)

_IMPROVEMENT_SIGNALS = re.compile(
    r"\b(improve|addition|architecture|limitation|precise|precision|accurate|"
    r"weakness|roadmap|build next|need)\b",
    re.IGNORECASE,
)


def is_product_meta_question(text: str) -> bool:
    """True when the user is asking about AIRA-X itself."""
    return bool(_META_REGEX.search(text or ""))


def manifest_context() -> str:
    """Compact truth block injected into the meta-answer prompt."""
    lines = [f"Identity: {MANIFEST['identity']}", "", "Current capabilities:"]
    lines += [f"- {item}" for item in MANIFEST["capabilities"]]
    lines += ["", "Known limitations:"]
    lines += [f"- {item}" for item in MANIFEST["limitations"]]
    lines += ["", "Architecture priorities (what to build next):"]
    lines += [f"- {item}" for item in MANIFEST["architecture_needs"]]
    lines += ["", f"Philosophy: {MANIFEST['philosophy']}"]
    return "\n".join(lines)


def offline_meta_answer(question: str) -> str:
    """Deterministic, manifest-grounded answer when no model is available."""
    if _IMPROVEMENT_SIGNALS.search(question or ""):
        bullets = "\n".join(f"- {item}" for item in MANIFEST["architecture_needs"][:6])
        return (
            "The highest-leverage improvements to my architecture right now:\n"
            f"{bullets}\n\n"
            f"Guiding principle: {MANIFEST['philosophy']}"
        )
    bullets = "\n".join(f"- {item}" for item in MANIFEST["capabilities"][:6])
    return f"{MANIFEST['identity']}\n\nWhat I can do today:\n{bullets}"
