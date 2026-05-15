from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_type: str
    title: str
    url: str | None = None
    document_id: int | None = None
    chunk_id: int | None = None
    page: int | None = None
    snippet: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: int
    document_id: int
    document_name: str
    chunk_index: int
    page: int | None = None
    text: str
    score: float = 0.0


class WebResult(BaseModel):
    title: str
    url: str
    summary: str
    source: str = "web"


class QueryPlan(BaseModel):
    rewritten_query: str
    needs_documents: bool = True
    needs_web: bool = False
    reason: str = ""


class AgentAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: str = "medium"
