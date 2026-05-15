from app.rag.schemas import QueryPlan


class QueryUnderstandingAgent:
    def plan(self, question: str) -> QueryPlan:
        cleaned_question = " ".join(question.strip().split())
        lower = cleaned_question.lower()

        latest_terms = [
            "latest",
            "current",
            "today",
            "recent",
            "news",
            "2026",
            "now",
            "web",
        ]

        document_terms = [
            "document",
            "paper",
            "pdf",
            "uploaded",
            "source",
            "summarize",
            "summary",
            "key points",
            "main points",
            "important points",
            "takeaways",
            "limitations",
            "methodology",
            "objectives",
            "findings",
            "conclusion",
            "explain this",
            "this document",
            "the document",
            "it",
            "this",
        ]

        follow_up_terms = [
            "it",
            "this",
            "that",
            "they",
            "them",
            "key points",
            "main points",
            "summarize",
            "summary",
            "explain more",
            "explain it",
            "list",
            "limitations",
            "advantages",
            "disadvantages",
            "takeaways",
            "what about",
            "tell me more",
        ]

        needs_web = any(term in lower for term in latest_terms)

        is_document_question = any(term in lower for term in document_terms)
        is_follow_up = any(term in lower for term in follow_up_terms)

        needs_documents = True if not needs_web else is_document_question

        rewritten = cleaned_question

        if is_follow_up and not needs_web:
            rewritten = (
                f"{cleaned_question} "
                "Answer using the currently uploaded document and the most relevant document chunks. "
                "Focus on the same document/topic discussed in the recent conversation."
            )

        reason = (
            "Detected web intent from recency terms."
            if needs_web
            else "Detected document or follow-up intent; using uploaded documents."
        )

        return QueryPlan(
            rewritten_query=rewritten,
            needs_documents=needs_documents,
            needs_web=needs_web,
            reason=reason,
        )