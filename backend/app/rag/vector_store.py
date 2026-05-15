import json
import math
from pathlib import Path

from app.core.config import settings
from app.rag.embeddings import get_embedding_function


class VectorStore:
    def __init__(self) -> None:
        self.path = Path(settings.vector_db_dir) / "vectors.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embeddings = get_embedding_function()
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def add_chunks(self, texts: list[str], metadatas: list[dict], ids: list[str]) -> None:
        records = self._load()
        existing_ids = {record["id"] for record in records}
        for text, metadata, vector_id in zip(texts, metadatas, ids):
            if vector_id in existing_ids:
                continue
            records.append(
                {
                    "id": vector_id,
                    "text": text,
                    "metadata": metadata,
                    "embedding": self.embeddings.embed(text),
                }
            )
        self._save(records)

    def search(self, query: str, k: int) -> list[tuple[str, dict, float]]:
        query_embedding = self.embeddings.embed(query)
        scored = []
        for record in self._load():
            score = self._cosine(query_embedding, record["embedding"])
            scored.append((record["text"], record["metadata"], score))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored[:k]

    def delete_document(self, document_id: int) -> None:
        records = [record for record in self._load() if record["metadata"].get("document_id") != document_id]
        self._save(records)

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, records: list[dict]) -> None:
        self.path.write_text(json.dumps(records), encoding="utf-8")

    def _cosine(self, left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
        right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
        return numerator / (left_norm * right_norm)
