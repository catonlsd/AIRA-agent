# File: backend/app/services/document_qa_service.py
"""
Document-first question answering.

Ingests documents into the vector store, retrieves the most relevant chunks for
a question, scores the evidence, and either answers grounded in the documents
(with citations) or says honestly that the answer is not in the uploaded files.

Backends are injected (embedding provider + vector store) so this is fully
testable with the dependency-free hashing provider and an ephemeral store.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence
from uuid import uuid4

from app.core.config import settings
from app.rag.chunker import chunk_pages
from app.rag.embedding_provider import EmbeddingProvider, get_embedding_provider
from app.rag.schemas import Citation, RetrievedChunk
from app.services.vector_store_service import VectorStore, get_document_vector_store
from app.turn_classifier import DOCUMENT_QA_MODE

# Minimum top-hit similarity to treat retrieved chunks as real evidence.
DEFAULT_MIN_EVIDENCE_SCORE = 0.15

# Whole-document requests (summaries/overviews) don't semantically match any
# single chunk, so they would score below the threshold even when documents are
# clearly present. For these, the presence of chunks is treated as sufficient
# evidence and more chunks are pulled for context.
_BROAD_REQUEST_PATTERNS = (
    "summariz", "summary", "tl;dr", "tldr", "overview", "key point", "main point",
    "key takeaway", "the gist", "what is this", "what's this", "whats this",
    "what is the document", "what is the file", "what does this", "what's in this",
    "whats in this", "brief me", "explain this document", "explain this file",
    "explain the document", "explain the file",
)
_BROAD_REQUEST_K = 8


def _is_broad_document_request(query: str) -> bool:
    lowered = query.lower()
    return any(pattern in lowered for pattern in _BROAD_REQUEST_PATTERNS)


def _citations_from_chunks(chunks: list[RetrievedChunk]) -> list[dict]:
    """Build de-duplicated document citations directly from retrieved chunks."""
    seen: set[tuple] = set()
    citations: list[dict] = []
    for chunk in chunks:
        key = (chunk.document_id, chunk.page, chunk.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                source_type="Document",
                title=chunk.document_name,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                page=chunk.page,
                snippet=chunk.text[:260],
            ).model_dump()
        )
    return citations


class DocumentQnAService:
    def __init__(
        self,
        *,
        embeddings: Optional[EmbeddingProvider] = None,
        store: Optional[VectorStore] = None,
        min_evidence_score: float = DEFAULT_MIN_EVIDENCE_SCORE,
    ) -> None:
        self.embeddings = embeddings or get_embedding_provider()
        self.store = store if store is not None else get_document_vector_store()
        self.min_evidence_score = min_evidence_score

    # ── Ingestion ────────────────────────────────────────────────────────────
    def ingest(
        self,
        *,
        document_id: int,
        document_name: str,
        pages: list[dict],
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
    ) -> int:
        chunks = chunk_pages(
            pages,
            chunk_size or settings.chunk_size,
            overlap or settings.chunk_overlap,
        )
        if not chunks:
            return 0

        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict] = []
        for index, chunk in enumerate(chunks):
            ids.append(f"{document_id}:{index}")
            texts.append(chunk["text"])
            metadata = {
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": index,
                "chunk_id": index,
            }
            if chunk.get("page") is not None:
                metadata["page"] = chunk["page"]
            metadatas.append(metadata)

        embeddings = self.embeddings.embed_documents(texts)
        self.store.add(ids, texts, metadatas, embeddings)
        return len(ids)

    def delete_document(self, document_id: int) -> None:
        self.store.delete({"document_id": document_id})

    # ── Retrieval ────────────────────────────────────────────────────────────
    def retrieve(self, query: str, k: Optional[int] = None) -> list[RetrievedChunk]:
        query_vector = self.embeddings.embed_query(query)
        hits = self.store.query(query_vector, k or settings.retrieval_k)

        chunks: list[RetrievedChunk] = []
        for text, metadata, score in hits:
            chunks.append(
                RetrievedChunk(
                    chunk_id=int(metadata.get("chunk_id", 0)),
                    document_id=int(metadata.get("document_id", 0)),
                    document_name=str(metadata.get("document_name", "")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    page=metadata.get("page"),
                    text=text,
                    score=float(score),
                )
            )
        return chunks

    # ── Answering ────────────────────────────────────────────────────────────
    def answer(
        self,
        query: str,
        *,
        history: Optional[Sequence[dict]] = None,
        k: Optional[int] = None,
    ) -> dict[str, Any]:
        broad_request = _is_broad_document_request(query)
        retrieve_k = k or settings.retrieval_k
        if broad_request:
            retrieve_k = max(retrieve_k, _BROAD_REQUEST_K)

        chunks = self.retrieve(query, retrieve_k)
        top_score = chunks[0].score if chunks else 0.0
        # For summarize/overview requests, having any document chunks is enough;
        # for specific questions, require the content-similarity threshold so we
        # stay honest when the answer genuinely isn't in the documents.
        has_evidence = bool(chunks) and (broad_request or top_score >= self.min_evidence_score)

        if not has_evidence:
            message = (
                "I looked through your uploaded documents but couldn't find enough "
                "relevant information to answer that confidently. You can rephrase the "
                "question, point me at a specific file or section, or ask me to answer "
                "from general knowledge or the web instead."
            )
            return self._result(
                decision="document_qa_insufficient_evidence",
                message=message,
                sources=[],
                has_evidence=False,
                top_score=top_score,
                chunk_count=len(chunks),
            )

        # Summarize/overview requests need a summarization prompt, not the
        # content-Q&A agent (whose "couldn't find" rule misfires on a meta query
        # like "summarize this document" even when the content is present).
        if broad_request:
            message = self._summarize_chunks(query, chunks)
            citations = _citations_from_chunks(chunks)
            return self._result(
                decision="document_qa_completed",
                message=message,
                sources=citations,
                has_evidence=True,
                top_score=top_score,
                chunk_count=len(chunks),
            )

        # Specific question: grounded answer + citations via the answer agent.
        from app.agents.answer_generation import AnswerGenerationAgent
        from app.agents.citation_verification import CitationVerificationAgent

        answer = AnswerGenerationAgent().answer(query, chunks, [], list(history or []), {})
        answer = CitationVerificationAgent().verify(answer)
        citations = [citation.model_dump() for citation in answer.citations]

        return self._result(
            decision="document_qa_completed",
            message=answer.answer,
            sources=citations,
            has_evidence=True,
            top_score=top_score,
            chunk_count=len(chunks),
        )

    def _summarize_chunks(self, query: str, chunks: list[RetrievedChunk]) -> str:
        from app.core.llm import LLMClient

        excerpts = "\n\n".join(
            f"[{c.document_name}, page {c.page if c.page is not None else 'n/a'}]\n{c.text}"
            for c in chunks
        )
        system = (
            "You are AIRA-X. Summarize the user's uploaded document content using ONLY "
            "the excerpts provided. Be clear and concise, capture the key points, and do "
            "not invent details. If the excerpts are limited, summarize what is available "
            "without saying the information is missing."
        )
        prompt = f"User request: {query}\n\nDocument excerpts:\n{excerpts}\n\nWrite the summary now."
        text = (LLMClient().generate(system, prompt) or "").strip()
        return text or "Here is a summary based on the uploaded document."

    def _result(
        self,
        *,
        decision: str,
        message: str,
        sources: list[dict],
        has_evidence: bool,
        top_score: float,
        chunk_count: int,
    ) -> dict[str, Any]:
        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": decision,
            "mode": DOCUMENT_QA_MODE,
            "message": message,
            "final_answer": message,
            "sources": sources,
            "artifacts": [],
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": bool(sources),
                "has_artifacts": False,
                "requires_approval": False,
                "has_evidence": has_evidence,
                "top_score": round(top_score, 4),
                "chunk_count": chunk_count,
            },
        }


_SERVICE: Optional[DocumentQnAService] = None


def get_document_qa_service() -> DocumentQnAService:
    """Process-wide cached service (shares the embedding model + vector client)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DocumentQnAService()
    return _SERVICE
