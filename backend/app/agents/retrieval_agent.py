from app.core.config import settings
from app.rag.schemas import RetrievedChunk
from app.rag.vector_store import VectorStore


class RetrievalAgent:
    def __init__(self) -> None:
        self.vector_store = VectorStore()

    def retrieve(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        results = self.vector_store.search(query, k or settings.retrieval_k)
        chunks = []
        for text, metadata, score in results:
            chunks.append(
                RetrievedChunk(
                    chunk_id=int(metadata["chunk_id"]),
                    document_id=int(metadata["document_id"]),
                    document_name=str(metadata["document_name"]),
                    chunk_index=int(metadata["chunk_index"]),
                    page=metadata.get("page"),
                    text=text,
                    score=float(score),
                )
            )
        return chunks
