# File: backend/app/rag/evidence.py
"""
Evidence sufficiency assessment for document-grounded answers.

The supervisor already distinguishes "answer from docs" vs "fall back to web".
This refines the *quality* of doc evidence into a strength signal used for honest
trust signalling and answer qualification — WITHOUT changing the existing
has-evidence/fallback contract.

`has_evidence` is computed by exactly the prior rule (any chunk for a broad
request, else top RAW vector score >= threshold). Only `none` means "no usable
evidence" (→ fallback). Among usable evidence we sub-classify:

    strong       — high score AND the query's terms are well covered
    partial      — usable, but only some of the question is covered by the docs
    weak         — usable by score, but little literal support (treat tentatively)
    conflicting  — on-topic chunks carry opposing claims (docs disagree)

Pure and deterministic: lexical coverage + a conservative polarity-contradiction
heuristic. No extra LLM calls — the gate stays cheap.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.reranker import _coverage, _terms
from app.rag.schemas import RetrievedChunk

STRENGTH_STRONG = "strong"
STRENGTH_PARTIAL = "partial"
STRENGTH_WEAK = "weak"
STRENGTH_NONE = "none"
STRENGTH_CONFLICTING = "conflicting"

# Polarity cues for the contradiction heuristic. Kept small and high-signal so it
# fires on genuine disagreement (e.g. "revenue grew" vs "revenue fell"), not on
# ordinary prose.
_POSITIVE_CUES = {
    "increase", "increased", "increases", "grew", "grow", "growth", "rose",
    "rise", "risen", "up", "higher", "gain", "gained", "improved", "positive",
    "approved", "success", "successful", "profit", "surplus", "yes", "supported",
}
_NEGATIVE_CUES = {
    "decrease", "decreased", "decreases", "fell", "fall", "fallen", "declined",
    "decline", "drop", "dropped", "down", "lower", "loss", "lost", "worsened",
    "negative", "rejected", "failure", "failed", "deficit", "no", "unsupported",
}


@dataclass
class EvidenceAssessment:
    strength: str
    has_evidence: bool
    coverage: float
    top_score: float
    reason: str


def _polarity(terms: set[str]) -> str | None:
    pos = bool(terms & _POSITIVE_CUES)
    neg = bool(terms & _NEGATIVE_CUES)
    if pos and not neg:
        return "positive"
    if neg and not pos:
        return "negative"
    return None


def _looks_conflicting(query_terms: set[str], chunks: list[RetrievedChunk]) -> bool:
    """True when on-topic top chunks carry opposing polarity about the question."""
    polarities: set[str] = set()
    for chunk in chunks[:4]:
        terms = _terms(chunk.text)
        # Only weigh chunks that actually touch the question.
        if query_terms and not (query_terms & terms):
            continue
        polarity = _polarity(terms)
        if polarity:
            polarities.add(polarity)
    return {"positive", "negative"} <= polarities


def assess_evidence(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    broad: bool,
    min_score: float,
) -> EvidenceAssessment:
    top_score = chunks[0].score if chunks else 0.0

    # Identical has-evidence rule to before: broad request needs any chunk; a
    # specific question needs the score threshold. This preserves the fallback
    # contract exactly — only `none` escalates to web.
    has_evidence = bool(chunks) and (broad or top_score >= min_score)
    if not has_evidence:
        return EvidenceAssessment(
            strength=STRENGTH_NONE,
            has_evidence=False,
            coverage=0.0,
            top_score=top_score,
            reason="no chunk cleared the evidence threshold",
        )

    # A summary/overview request is grounded in whatever the document holds; the
    # query intentionally doesn't match a single chunk, so don't down-rank it.
    if broad:
        return EvidenceAssessment(
            strength=STRENGTH_STRONG,
            has_evidence=True,
            coverage=1.0,
            top_score=top_score,
            reason="broad request grounded in document content",
        )

    query_terms = _terms(query)
    covered = max(
        (_coverage(query_terms, _terms(chunk.text)) for chunk in chunks[:4]),
        default=0.0,
    )

    if _looks_conflicting(query_terms, chunks):
        return EvidenceAssessment(
            strength=STRENGTH_CONFLICTING,
            has_evidence=True,
            coverage=covered,
            top_score=top_score,
            reason="documents carry opposing claims about the question",
        )
    if covered >= 0.5:
        strength, reason = STRENGTH_STRONG, "high score with strong term coverage"
    elif covered >= 0.25:
        strength, reason = STRENGTH_PARTIAL, "usable but only partial coverage"
    else:
        strength, reason = STRENGTH_WEAK, "usable by score but little literal support"

    return EvidenceAssessment(
        strength=strength,
        has_evidence=True,
        coverage=covered,
        top_score=top_score,
        reason=reason,
    )
