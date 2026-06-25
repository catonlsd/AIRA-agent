# File: backend/tests/test_retrieval_quality.py
"""Retrieval quality upgrade: section/page-aware chunking, a reranking layer
(blended relevance + de-duplication), evidence-strength assessment (strong /
partial / weak / none / conflicting), and clean grounded composition with honest
trust qualifiers. No vector internals leak into user-facing text."""

from uuid import uuid4

import pytest

from app.rag.chunker import chunk_pages
from app.rag.embedding_provider import HashingEmbeddingProvider
from app.rag.evidence import (
    STRENGTH_CONFLICTING,
    STRENGTH_NONE,
    STRENGTH_PARTIAL,
    STRENGTH_STRONG,
    assess_evidence,
)
from app.rag.reranker import LexicalReranker
from app.rag.schemas import RetrievedChunk
from app.services.document_qa_service import (
    DocumentQnAService,
    _apply_trust_qualifier,
)
from app.services.vector_store_service import ChromaVectorStore


def _chunk(text, *, score, doc=1, cid=0, page=1):
    return RetrievedChunk(
        chunk_id=cid, document_id=doc, document_name="d.pdf",
        chunk_index=cid, page=page, text=text, score=score,
    )


def _service():
    return DocumentQnAService(
        embeddings=HashingEmbeddingProvider(),
        store=ChromaVectorStore(f"rq_{uuid4().hex[:10]}", ephemeral=True),
    )


# ── Chunking policy ──────────────────────────────────────────────────────────


def test_chunking_keeps_section_and_page_metadata():
    pages = [
        {"page": 3, "text": "Introduction\n\nThis report covers revenue and costs for 2025.\n\n"
                            "Methodology\n\nWe used standard accounting practices throughout."},
    ]
    chunks = chunk_pages(pages, chunk_size=80, overlap=20)
    assert chunks  # produced something
    # Page provenance is preserved on every chunk.
    assert all(c["page"] == 3 for c in chunks)
    # Heading boundaries became sections, and the heading rides with its body.
    sections = {c.get("section") for c in chunks}
    assert "Introduction" in sections and "Methodology" in sections
    intro = next(c for c in chunks if c.get("section") == "Introduction")
    assert intro["text"].startswith("Introduction")
    assert "revenue and costs" in intro["text"]


def test_chunking_does_not_cross_page_boundaries():
    pages = [
        {"page": 1, "text": "Alpha content on page one."},
        {"page": 2, "text": "Beta content on page two."},
    ]
    chunks = chunk_pages(pages, chunk_size=500, overlap=50)
    assert len(chunks) == 2
    assert {c["page"] for c in chunks} == {1, 2}
    # No chunk merges text from both pages.
    assert all(not ("Alpha" in c["text"] and "Beta" in c["text"]) for c in chunks)


def test_chunking_short_doc_is_a_single_clean_chunk():
    # Parity-style short page: one paragraph, no headings -> one chunk, no section,
    # text unchanged (keeps the legacy/new retrieval paths identical).
    pages = [{"page": 1, "text": "Revenue grew 40 percent in 2025."}]
    chunks = chunk_pages(pages, chunk_size=1000, overlap=150)
    assert chunks == [{"text": "Revenue grew 40 percent in 2025.", "section": None, "page": 1}]


def test_chunking_long_paragraph_is_split_no_degenerate_chunks():
    big = " ".join(f"word{i}" for i in range(400))
    chunks = chunk_pages([{"page": 1, "text": big}], chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(c["text"].strip() for c in chunks)  # no empty/degenerate chunks


# ── Reranking layer ──────────────────────────────────────────────────────────


def test_reranker_promotes_lexically_relevant_chunk_over_nearest_vector():
    reranker = LexicalReranker()
    chunks = [
        _chunk("An unrelated paragraph about gardening tools.", score=0.40, cid=1),
        _chunk("The migration patterns of arctic terns span the globe.", score=0.35, cid=2),
    ]
    ranked = reranker.rerank("arctic tern migration patterns", chunks, top_k=2)
    # Despite a lower vector score, the on-topic chunk is promoted to the top.
    assert ranked[0].chunk_id == 2


def test_reranker_drops_near_duplicate_chunks():
    reranker = LexicalReranker()
    base = "Revenue grew forty percent in the 2025 fiscal year across all regions."
    chunks = [
        _chunk(base, score=0.50, cid=1),
        _chunk(base + " It was a record.", score=0.49, cid=2),  # near-duplicate
        _chunk("Operating costs stayed flat compared to last year.", score=0.30, cid=3),
    ]
    ranked = reranker.rerank("how did revenue change", chunks, top_k=3)
    texts = [c.chunk_id for c in ranked]
    assert 1 in texts and 3 in texts
    assert 2 not in texts  # the overlapping duplicate is de-prioritised


def test_reranker_preserves_raw_vector_score_semantics():
    reranker = LexicalReranker()
    chunks = [_chunk("revenue grew", score=0.42, cid=1)]
    ranked = reranker.rerank("revenue", chunks, top_k=1)
    assert ranked[0].score == 0.42  # score is still the raw similarity, not blended


# ── Evidence sufficiency ─────────────────────────────────────────────────────


def test_strong_evidence_is_detected():
    chunks = [_chunk("Python is used for web development and data analysis.", score=0.6)]
    a = assess_evidence("what is python used for", chunks, broad=False, min_score=0.15)
    assert a.strength == STRENGTH_STRONG and a.has_evidence is True


def test_partial_evidence_is_detected():
    # Decent score, but the chunk only covers part of the multi-term question.
    chunks = [_chunk("Python supports data analysis.", score=0.5)]
    a = assess_evidence(
        "explain python deployment kubernetes scaling data analysis",
        chunks, broad=False, min_score=0.15,
    )
    assert a.strength == STRENGTH_PARTIAL and a.has_evidence is True


def test_no_evidence_when_below_threshold():
    chunks = [_chunk("totally unrelated text", score=0.05)]
    a = assess_evidence("quantum chromodynamics", chunks, broad=False, min_score=0.15)
    assert a.strength == STRENGTH_NONE and a.has_evidence is False


def test_no_evidence_when_empty():
    a = assess_evidence("anything", [], broad=False, min_score=0.15)
    assert a.strength == STRENGTH_NONE and a.has_evidence is False


def test_conflicting_evidence_is_identified_honestly():
    chunks = [
        _chunk("Revenue grew and rose sharply in 2025.", score=0.6, cid=1),
        _chunk("Revenue fell and declined in 2025.", score=0.58, cid=2),
    ]
    a = assess_evidence("what happened to revenue", chunks, broad=False, min_score=0.15)
    assert a.strength == STRENGTH_CONFLICTING and a.has_evidence is True


def test_broad_request_is_grounded_strong_with_any_chunk():
    chunks = [_chunk("Some document body text.", score=0.05)]
    a = assess_evidence("summarize this file", chunks, broad=True, min_score=0.15)
    assert a.strength == STRENGTH_STRONG and a.has_evidence is True


# ── Grounded composition + trust qualifiers (no internals leak) ──────────────


def test_strong_answer_has_no_qualifier():
    out = _apply_trust_qualifier("Python is used for web and data work.", STRENGTH_STRONG)
    assert out == "Python is used for web and data work."


def test_partial_and_weak_answers_get_honest_notes():
    partial = _apply_trust_qualifier("The answer is X.", STRENGTH_PARTIAL)
    assert "partially cover" in partial and partial.startswith("The answer is X.")
    weak = _apply_trust_qualifier("The answer is Y.", "weak")
    assert "limited information" in weak


def test_conflicting_answer_is_framed_up_front():
    out = _apply_trust_qualifier("Some say up, some say down.", STRENGTH_CONFLICTING)
    assert out.startswith("Your uploaded files appear inconsistent")


def test_qualifiers_never_leak_vector_internals():
    for strength in ("partial", "weak", STRENGTH_CONFLICTING):
        text = _apply_trust_qualifier("Body.", strength).lower()
        for banned in ("chunk", "collection", "embedding", "vector", "score", "cosine"):
            assert banned not in text


# ── End-to-end through the service: strength surfaces in meta ────────────────


def test_service_surfaces_evidence_strength_in_meta():
    service = _service()
    service.ingest(
        document_id=7, document_name="python.txt",
        pages=[{"page": 1, "text": "Python is used for web development and data analysis."}],
    )
    result = service.answer("what is python used for?")
    assert result["decision"] == "document_qa_completed"
    assert result["meta"]["evidence_strength"] in (
        STRENGTH_STRONG, STRENGTH_PARTIAL, "weak",
    )
    # Never leak retrieval internals into the user-facing answer.
    lowered = result["message"].lower()
    assert "chunk" not in lowered and "collection" not in lowered


def test_offtopic_question_reports_none_strength():
    service = _service()
    service.ingest(
        document_id=7, document_name="python.txt",
        pages=[{"page": 1, "text": "Python is used for web development and data analysis."}],
    )
    result = service.answer("describe the migration patterns of arctic terns")
    assert result["meta"]["has_evidence"] is False
    assert result["meta"]["evidence_strength"] == STRENGTH_NONE


def test_owner_scoping_is_preserved_through_rerank():
    service = _service()
    service.ingest(document_id=1, document_name="a.pdf",
                   pages=[{"page": 1, "text": "Alpha owns apples and oranges."}], owner="alice")
    service.ingest(document_id=2, document_name="b.pdf",
                   pages=[{"page": 1, "text": "Beta owns bananas and grapes."}], owner="bob")
    result = service.answer("what fruit is owned", owner="alice")
    # Only alice's document may surface, even after reranking.
    for source in result["sources"]:
        assert source["title"] == "a.pdf"
