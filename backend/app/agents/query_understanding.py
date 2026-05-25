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
            "now",
            "web",
            "internet",
            "online",
            "search",
            "look up",
            "browse",
        ]

        document_terms = [
            "document",
            "documents",
            "paper",
            "pdf",
            "uploaded",
            "upload",
            "file",
            "files",
            "source",
            "sources",
            "knowledge base",
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
            "explain this document",
            "this document",
            "the document",
            "this pdf",
            "the pdf",
            "this file",
            "the file",
            "from my document",
            "from the document",
            "based on my document",
            "based on the document",
            "according to the document",
            "according to my file",
        ]

        follow_up_terms = [
            "summarize it",
            "explain it",
            "explain this",
            "tell me more about it",
            "what about this",
            "what about that",
            "list the key points",
            "list main points",
            "what are the key points",
            "what are the main points",
            "give me the overview",
        ]

        needs_web = any(term in lower for term in latest_terms)
        is_document_question = any(term in lower for term in document_terms)
        is_follow_up = any(term in lower for term in follow_up_terms)

        # Important:
        # Do NOT default every question to documents.
        # Casual and general questions should be answerable without RAG.
        # Documents are used only when the user clearly asks about uploaded/source content.
        needs_documents = is_document_question or (is_follow_up and not needs_web)

        rewritten = cleaned_question

        if needs_documents and is_follow_up and not needs_web:
            rewritten = (
                f"{cleaned_question} "
                "Answer using the currently uploaded document and the most relevant document chunks. "
                "Focus on the same document/topic discussed in the recent conversation."
            )

        if needs_web:
            reason = "Detected web intent from recency/search terms."
        elif needs_documents:
            reason = "Detected uploaded-document intent; using retrieved document chunks."
        else:
            reason = "Detected general conversation intent; answer without document retrieval."

        return QueryPlan(
            rewritten_query=rewritten,
            needs_documents=needs_documents,
            needs_web=needs_web,
            reason=reason,
        )
