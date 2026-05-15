import re

from app.rag.schemas import AgentAnswer


class CitationVerificationAgent:
    def verify(self, answer: AgentAnswer) -> AgentAnswer:
        unsupported_phrases = [
            "the provided sources do not contain enough information",
            "i could not verify this from the available sources",
        ]

        answer_lower = answer.answer.lower()

        if any(phrase in answer_lower for phrase in unsupported_phrases):
            answer.citations = []
            answer.confidence = "low"
            return answer

        # Do NOT overwrite a valid answer just because citation filtering removed citations.
        if not answer.citations:
            answer.confidence = "low"
            return answer

        answer.confidence = "medium"
        return answer