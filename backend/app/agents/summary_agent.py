from app.core.llm import LLMClient
from app.rag.schemas import Citation


class SummaryAgent:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def summarize(self, title: str, chunks: list[dict]) -> dict:
        document_context = "\n\n".join(
            [
                f"Page: {c.get('page') or 'Not available'}\nContent:\n{c['text']}"
                for c in chunks[:20]
            ]
        )

        system = """
You are an AI Research Assistant.

Create a clean, professional document summary.

Rules:
1. Do not mention chunk numbers.
2. Do not mention chunk IDs or retrieval metadata.
3. Do not write phrases like "Chunk 1", "Citation:", or "retrieved context".
4. Use clear sections.
5. Include:
   - Overview
   - Key Points
   - Important Details
   - Limitations or Gaps
   - Final Takeaway
6. Mention page numbers only when useful.
7. Keep the tone professional and easy to understand.
"""

        prompt = f"""
Document title:
{title}

Document content:
{document_context}

Write the final summary now.
"""

        summary = self.llm.generate(system, prompt)

        citations = [
            Citation(
                source_type="Document",
                title=title,
                document_id=c.get("document_id"),
                chunk_id=c.get("id"),
                page=c.get("page"),
                snippet=c["text"][:220],
            ).model_dump()
            for c in chunks[:8]
        ]

        return {
            "summary": summary.strip(),
            "citations": citations,
        }