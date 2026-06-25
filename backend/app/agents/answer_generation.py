import re

from app.core.llm import LLMClient
from app.rag.schemas import AgentAnswer, Citation, RetrievedChunk, WebResult


class AnswerGenerationAgent:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def answer(
        self,
        question: str,
        doc_chunks: list[RetrievedChunk],
        web_results: list[WebResult],
        history: list[dict],
        preferences: dict,
    ) -> AgentAnswer:
        citations: list[Citation] = []
        document_sources = []
        web_sources = []

        for idx, chunk in enumerate(doc_chunks, start=1):
            document_sources.append(
                f"Document Source {idx}\n"
                f"Title: {chunk.document_name}\n"
                f"Page: {chunk.page or 'Not available'}\n"
                f"Content:\n{chunk.text}"
            )
            citations.append(
                Citation(
                    source_type="Document",
                    title=chunk.document_name,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    page=chunk.page,
                    snippet=chunk.text[:260],
                )
            )

        for idx, result in enumerate(web_results, start=1):
            web_sources.append(
                f"Web Source {idx}\n"
                f"Title: {result.title}\n"
                f"URL: {result.url}\n"
                f"Content:\n{result.summary}"
            )
            citations.append(
                Citation(
                    source_type="Web",
                    title=result.title,
                    url=result.url,
                    snippet=result.summary[:260],
                )
            )

        # If no sources were retrieved at all, fall back to the LLM's own knowledge.
        # This handles general questions, weather queries without a web result,
        # conversational follow-ups, etc. — never show the "sources don't contain"
        # message for queries that weren't about uploaded documents.
        if not document_sources and not web_sources:
            return self._general_answer(question, history, preferences)

        return self._source_grounded_answer(
            question=question,
            document_sources=document_sources,
            web_sources=web_sources,
            citations=citations,
            history=history,
            preferences=preferences,
        )

    def _general_answer(
        self,
        question: str,
        history: list[dict],
        preferences: dict,
    ) -> AgentAnswer:
        # Only show the document-specific message when the user actually asked
        # about an uploaded document and we have nothing.
        if self._looks_like_document_request(question):
            return AgentAnswer(
                answer=(
                    "I could not find enough relevant uploaded document content "
                    "to answer that confidently. Please upload the document first, "
                    "or try asking about a specific uploaded file, section, topic, "
                    "or page."
                ),
                citations=[],
                confidence="low",
            )

        system = """
You are AIRA-X, a polished AI research and general assistant.

You can answer normal everyday questions, explain concepts, help with learning,
coding, project planning, writing, research, weather, current events, and document work.

Rules:
1. Answer naturally, directly, and helpfully using your own knowledge.
2. For weather questions, provide a general helpful answer based on typical
   patterns for the location/season if you cannot get live data, and note that
   live forecasts may vary. Never say sources are missing for weather queries.
3. Do not claim you used uploaded documents unless document sources are provided.
4. Do not mention missing sources for general or everyday questions.
5. Do not include a Sources section for general answers.
6. Do not fabricate citations.
7. Keep the tone friendly, clear, and professional.
8. For simple greetings or small talk, reply briefly and warmly.
9. For educational or technical questions, give a helpful structured answer.
10. NEVER say "The provided sources do not contain enough information" for
    general knowledge, weather, or everyday questions. That message is only
    for cases where the user explicitly asked about an uploaded document and
    nothing was found.
11. If the question genuinely requires live real-time data you cannot access
    (e.g. exact current stock price, live sports score), acknowledge that
    clearly and offer what general context you can.
"""

        prompt = f"""
User question:
{question}

Recent conversation summary:
{history if history else "No recent conversation."}

User preferences:
{preferences if preferences else "No saved preferences."}

Write the final answer now. Be direct and helpful.
"""

        text = self.llm.generate(system, prompt).strip()

        if not text:
            text = "I'm ready to help. Could you tell me what you want to work on?"

        return AgentAnswer(
            answer=text,
            citations=[],
            confidence="medium",
        )

    def _source_grounded_answer(
        self,
        question: str,
        document_sources: list[str],
        web_sources: list[str],
        citations: list[Citation],
        history: list[dict],
        preferences: dict,
    ) -> AgentAnswer:
        system = """
You are AIRA-X, an AI Research Assistant.

Your job is to answer using the provided document sources and web sources.

Rules:
1. Give a clear, direct, professional answer.
2. Use headings and bullet points when helpful.
3. Do not mention chunk numbers, chunk IDs, raw retrieval data, JSON, or internal metadata.
4. Do not use inline labels like [D1], [D2], [W1], or [W2].
5. Do not say "based on the context" repeatedly.
6. If web sources are provided and they contain relevant information, use them
   to answer fully and accurately. Prefer web sources for live/current data.
7. If the provided sources genuinely do not contain useful information AND the
   question is about an uploaded document, say:
   "I could not find relevant information in the uploaded documents for this query."
   NEVER use the phrase "The provided sources do not contain enough information
   to answer this confidently" — it sounds like an error message.
8. If the sources are about documents but the question is general (weather, facts,
   etc.), answer from your own knowledge and note that web results were limited.
9. At the end, include a clean Sources section only when sources are actually used.
10. For document sources, use this format:
    - Document name — Page X
11. For web sources, use this format:
    - Page/article title — URL
12. Only include sources that are actually relevant to the answer.
13. If the answer comes from web sources only, do not list document sources.
14. If the uploaded documents do not contain the answer, do not mention them in Sources.
"""

        prompt = f"""
User question:
{question}

Recent conversation summary:
{history if history else "No recent conversation."}

User preferences:
{preferences if preferences else "No saved preferences."}

Document sources:
{chr(10).join(document_sources) if document_sources else "No document sources provided."}

Web sources:
{chr(10).join(web_sources) if web_sources else "No web sources provided."}

Write the final answer now. Be direct and helpful.
"""

        text = self.llm.generate(system, prompt).strip()
        filtered_citations = self._filter_relevant_citations(text, citations)

        if self._is_unsupported_source_answer(text):
            return AgentAnswer(
                answer=text,
                citations=[],
                confidence="low",
            )

        return AgentAnswer(
            answer=text,
            citations=filtered_citations,
            confidence="medium" if filtered_citations else "medium",
        )

    def _looks_like_document_request(self, question: str) -> bool:
        lower = question.lower()

        document_terms = [
            "uploaded document", "uploaded file",
            "my document", "my file",
            "the document", "this document",
            "the pdf", "this pdf",
            "summarize document", "summarize the document",
            "summarize my document", "summarize uploaded",
            "according to the document", "based on the document",
            "from the document", "from my file",
            "in the pdf", "knowledge base",
        ]

        return any(term in lower for term in document_terms)

    def _is_unsupported_source_answer(self, answer: str) -> bool:
        # Detect the old unhelpful message in case the LLM still generates it
        # so we can strip citations from it.
        unsupported_phrases = [
            "the provided sources do not contain enough information",
            "i could not find relevant information in the uploaded documents",
        ]
        lower = answer.lower()
        return any(phrase in lower for phrase in unsupported_phrases)

    def _filter_relevant_citations(
        self,
        answer: str,
        citations: list[Citation],
    ) -> list[Citation]:
        if self._is_unsupported_source_answer(answer):
            return []

        answer_without_sources = re.split(
            r"\n\s*(sources|references)\s*:?\s*\n",
            answer,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        answer_words = self._important_words(answer_without_sources)

        if not answer_words:
            return []

        relevant: list[Citation] = []

        for citation in citations:
            searchable_text = " ".join([
                citation.title or "",
                citation.snippet or "",
                citation.url or "",
            ])

            citation_words = self._important_words(searchable_text)
            overlap = answer_words.intersection(citation_words)
            min_required_overlap = 2 if citation.source_type.lower() == "web" else 3

            if len(overlap) >= min_required_overlap:
                relevant.append(citation)

        return relevant

    def _important_words(self, text: str) -> set[str]:
        stopwords = {
            "about", "after", "again", "against", "also", "answer",
            "because", "before", "being", "between", "could", "country",
            "document", "during", "first", "from", "have", "into",
            "more", "most", "only", "other", "page", "provided",
            "question", "research", "section", "should", "source",
            "sources", "their", "there", "these", "they", "this",
            "those", "through", "using", "which", "while", "with",
            "would", "your",
        }

        words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{3,}", text.lower())

        return {
            word.strip("-")
            for word in words
            if word.strip("-") and word.strip("-") not in stopwords
        }