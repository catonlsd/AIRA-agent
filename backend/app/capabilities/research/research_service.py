# File: backend/app/capabilities/research/research_service.py
"""
Research capability.

Wraps the existing research stack (query understanding -> retrieval / web search
-> answer generation -> citation verification) into one service the supervisor
calls for web-research and (later) document-first turns. Returns a normalized
result dict in the shared response shape.

This service is DB-light: retrieval reads from the vector store directly, and
conversation history/preferences are passed in from the turn context.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence
from uuid import uuid4

from app.agents.answer_generation import AnswerGenerationAgent
from app.agents.citation_verification import CitationVerificationAgent
from app.agents.query_understanding import QueryUnderstandingAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.agents.web_research_agent import WebResearchAgent
from app.turn_classifier import DOCUMENT_QA_MODE, WEB_RESEARCH_MODE


class ResearchService:
    """Grounded answer generation over web and/or document sources."""

    def run(
        self,
        message: str,
        *,
        history: Optional[Sequence[dict]] = None,
        preferences: Optional[dict] = None,
        want_web: bool = True,
        want_documents: bool = False,
        mode: str = WEB_RESEARCH_MODE,
    ) -> dict[str, Any]:
        history = list(history or [])
        preferences = dict(preferences or {})

        plan = QueryUnderstandingAgent().plan(message)
        plan.needs_web = want_web
        plan.needs_documents = want_documents

        doc_chunks = (
            RetrievalAgent().retrieve(plan.rewritten_query) if want_documents else []
        )
        web_results = (
            WebResearchAgent().search(plan.rewritten_query) if want_web else []
        )

        answer = AnswerGenerationAgent().answer(
            message,
            doc_chunks,
            web_results,
            history,
            preferences,
        )
        answer = CitationVerificationAgent().verify(answer)

        citations = [citation.model_dump() for citation in answer.citations]
        decision = (
            "document_qa_completed" if mode == DOCUMENT_QA_MODE else "web_research_completed"
        )

        return {
            "run_id": uuid4().hex,
            "status": "completed",
            "decision": decision,
            "mode": mode,
            "message": answer.answer,
            "final_answer": answer.answer,
            "sources": citations,
            "artifacts": [],
            "approval_summary": None,
            "meta": {
                "is_multi_question": False,
                "question_count": 1,
                "has_sources": bool(citations),
                "has_artifacts": False,
                "requires_approval": False,
                "web_results_count": len(web_results),
                "document_chunks_count": len(doc_chunks),
            },
        }
