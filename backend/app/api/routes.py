from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.answer_generation import AnswerGenerationAgent
from app.agents.citation_verification import CitationVerificationAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.query_understanding import QueryUnderstandingAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.agents.summary_agent import SummaryAgent
from app.agents.web_research_agent import WebResearchAgent
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Document, DocumentChunk
from app.memory.service import MemoryService
from app.rag.chunker import chunk_pages
from app.rag.document_loader import SUPPORTED_EXTENSIONS, extract_text
from app.rag.schemas import RetrievedChunk
from app.rag.vector_store import VectorStore

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    use_web: bool = False


class SummarizeRequest(BaseModel):
    document_id: int


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


def validate_upload_file(file: UploadFile) -> str:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    clean_extension = suffix.replace(".", "")

    allowed_extensions = set(settings.allowed_file_extensions)

    if clean_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix}'. Allowed types: "
                f"{', '.join(sorted(allowed_extensions))}"
            ),
        )

    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{suffix}' is not supported by the document parser."
            ),
        )

    return suffix


def save_upload_file(file: UploadFile, stored_path: Path) -> int:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    total_size = 0

    with stored_path.open("wb") as buffer:
        while True:
            chunk = file.file.read(1024 * 1024)

            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_bytes:
                buffer.close()

                if stored_path.exists():
                    stored_path.unlink()

                raise HTTPException(
                    status_code=413,
                    detail=(
                        "File too large. Maximum allowed size is "
                        f"{settings.max_upload_size_mb} MB."
                    ),
                )

            buffer.write(chunk)

    return total_size


def normalize_message_text(text: str) -> str:
    normalized = text.lower().strip()

    for old, new in {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "?": "",
        "!": "",
        ".": "",
        ",": "",
        ":": "",
        ";": "",
    }.items():
        normalized = normalized.replace(old, new)

    return " ".join(normalized.split())


def matches_any(normalized: str, phrases: set[str]) -> bool:
    return normalized in phrases or any(
        normalized.startswith(f"{phrase} ") for phrase in phrases
    )


def get_casual_chat_response(question: str) -> dict | None:
    normalized = normalize_message_text(question)

    greeting_messages = {
        "hi",
        "hii",
        "hello",
        "hey",
        "heyy",
        "yo",
        "namaste",
        "good morning",
        "good afternoon",
        "good evening",
    }

    wellbeing_messages = {
        "how are you",
        "how r u",
        "how are u",
        "how are you doing",
        "how is it going",
        "hows it going",
        "what's up",
        "whats up",
        "sup",
    }

    activity_messages = {
        "what are you doing",
        "what r you doing",
        "what are u doing",
        "what do you do",
        "what are you working on",
        "what is your work",
    }

    thanks_messages = {
        "thanks",
        "thank you",
        "thank u",
        "ty",
        "okay thanks",
        "ok thanks",
        "great thanks",
    }

    goodbye_messages = {
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "talk to you later",
    }

    capability_messages = {
        "help",
        "what can you do",
        "what can u do",
        "how can you help",
        "how can u help",
        "how can you assist me",
        "how can u assist me",
        "how can you assist",
        "how can you support me",
        "how can you be useful",
        "what can aira do",
        "who are you",
        "what is aira",
        "what is aira x",
        "what is aira-x",
        "tell me about aira",
        "tell me about yourself",
    }

    if matches_any(normalized, greeting_messages):
        return {
            "answer": (
                "Hey! I’m AIRA. You can ask me a normal question, upload "
                "documents for source-backed answers, or switch to AIRA-X "
                "when you want tasks planned and executed."
            ),
            "intent": "casual_chat",
            "confidence": "high",
        }

    if matches_any(normalized, wellbeing_messages):
        return {
            "answer": (
                "I’m doing great and ready to help. You can ask me a general "
                "question, ask about uploaded documents, request summaries, or "
                "switch to AIRA-X for execution workflows."
            ),
            "intent": "casual_chat",
            "confidence": "high",
        }

    if matches_any(normalized, activity_messages):
        return {
            "answer": (
                "I’m ready to help you research, understand documents, summarize "
                "sources, answer general questions, and support AIRA-X workflows "
                "when you want tasks executed."
            ),
            "intent": "casual_chat",
            "confidence": "high",
        }

    if matches_any(normalized, thanks_messages):
        return {
            "answer": (
                "You’re welcome! Send me the next question whenever you’re ready."
            ),
            "intent": "casual_chat",
            "confidence": "high",
        }

    if matches_any(normalized, goodbye_messages):
        return {
            "answer": "See you! I’ll be ready when you want to continue.",
            "intent": "casual_chat",
            "confidence": "high",
        }

    if matches_any(normalized, capability_messages):
        return {
            "answer": (
                "I can help in two modes:\n\n"
                "AIRA mode: I can answer general questions, upload and read "
                "documents, summarize sources, retrieve relevant context, and "
                "return citation-backed answers when documents are involved.\n\n"
                "AIRA-X mode: I can turn a task into an execution workflow, plan "
                "steps, use tools, pause for approval on risky actions, validate "
                "results, and keep workflow logs."
            ),
            "intent": "capability_help",
            "confidence": "high",
        }

    return None


def build_direct_chat_response(
    question: str,
    answer_text: str,
    intent: str,
    confidence: str,
    db: Session,
) -> dict:
    citations: list[dict] = []

    MemoryAgent().store_turn(db, question, answer_text, citations)

    return {
        "answer": answer_text,
        "citations": citations,
        "plan": {
            "intent": intent,
            "rewritten_query": question,
            "needs_documents": False,
            "needs_web": False,
        },
        "confidence": confidence,
        "metadata": {
            "route": intent,
            "web_enabled": False,
            "web_results_count": 0,
            "document_chunks_count": 0,
        },
    }


def is_vague_document_followup(question: str) -> bool:
    lower = question.lower().strip()

    followup_phrases = [
        "what is this document about",
        "what is the document about",
        "summarize this document",
        "summarize the document",
        "summarize it",
        "summary",
        "list the key points",
        "key points",
        "main points",
        "important points",
        "what are the key points",
        "explain this",
        "explain it",
        "tell me more",
        "give me the overview",
        "overview",
    ]

    return any(phrase in lower for phrase in followup_phrases)


def latest_document_chunks(db: Session, limit: int = 12) -> list[RetrievedChunk]:
    document = db.query(Document).order_by(Document.created_at.desc()).first()

    if not document:
        return []

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(limit)
        .all()
    )

    return [
        RetrievedChunk(
            document_id=document.id,
            document_name=document.original_filename,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            page=chunk.page,
            text=chunk.text,
        )
        for chunk in chunks
    ]


def build_contextual_query(question: str, history: list[dict]) -> str:
    if not history:
        return question

    recent_context = " ".join(
        item.get("content", "")
        for item in history[-4:]
        if isinstance(item, dict)
    )

    if not recent_context.strip():
        return question

    return f"{question}\n\nRecent conversation context:\n{recent_context}"


@router.post("/upload")
def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    uploaded = []
    vector_store = VectorStore()

    for file in files:
        suffix = validate_upload_file(file)

        stored_name = f"{uuid4().hex}{suffix}"
        stored_path = Path(settings.upload_dir) / stored_name

        try:
            file_size = save_upload_file(file, stored_path)

            pages = extract_text(str(stored_path))
            chunks = chunk_pages(
                pages,
                settings.chunk_size,
                settings.chunk_overlap,
            )

            if not chunks:
                if stored_path.exists():
                    stored_path.unlink()

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"No readable text found in '{file.filename}'. "
                        "Please upload a text-based document."
                    ),
                )

            document = Document(
                filename=stored_name,
                original_filename=file.filename or stored_name,
                file_type=suffix.replace(".", ""),
                path=str(stored_path),
                chunk_count=len(chunks),
            )

            db.add(document)
            db.flush()

            texts, metadatas, vector_ids = [], [], []

            for index, chunk in enumerate(chunks):
                vector_id = f"doc-{document.id}-chunk-{index}"

                row = DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    page=chunk.get("page"),
                    text=chunk["text"],
                    vector_id=vector_id,
                )

                db.add(row)
                db.flush()

                texts.append(chunk["text"])
                metadatas.append(
                    {
                        "document_id": document.id,
                        "document_name": document.original_filename,
                        "chunk_id": row.id,
                        "chunk_index": index,
                        "page": chunk.get("page") or 0,
                    }
                )
                vector_ids.append(vector_id)

            vector_store.add_chunks(texts, metadatas, vector_ids)
            db.commit()

            uploaded.append(
                {
                    "id": document.id,
                    "filename": document.original_filename,
                    "file_type": document.file_type,
                    "chunks": len(chunks),
                    "size_bytes": file_size,
                    "status": "processed",
                }
            )

        except HTTPException:
            db.rollback()
            raise

        except Exception as error:
            db.rollback()

            if stored_path.exists():
                stored_path.unlink()

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to process '{file.filename}'. "
                    "Please try another file."
                ),
            ) from error

    return {
        "message": "Documents uploaded and indexed successfully.",
        "documents": uploaded,
    }


@router.post("/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> dict:
    question = payload.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    casual_response = get_casual_chat_response(question)

    if casual_response:
        return build_direct_chat_response(
            question=question,
            answer_text=casual_response["answer"],
            intent=casual_response["intent"],
            confidence=casual_response["confidence"],
            db=db,
        )

    try:
        memory_agent = MemoryAgent()
        history, preferences = memory_agent.context(db)

        planner = QueryUnderstandingAgent()
        plan = planner.plan(question)

        plan.needs_web = payload.use_web

        if plan.needs_documents:
            if is_vague_document_followup(question):
                doc_chunks = latest_document_chunks(db, limit=12)
            else:
                contextual_query = build_contextual_query(
                    plan.rewritten_query,
                    history,
                )
                doc_chunks = RetrievalAgent().retrieve(contextual_query)
        else:
            doc_chunks = []

        web_results = (
            WebResearchAgent().search(plan.rewritten_query)
            if plan.needs_web
            else []
        )

        answer = AnswerGenerationAgent().answer(
            question,
            doc_chunks,
            web_results,
            history,
            preferences,
        )

        answer = CitationVerificationAgent().verify(answer)
        citations = [citation.model_dump() for citation in answer.citations]

        memory_agent.store_turn(db, question, answer.answer, citations)

        return {
            "answer": answer.answer,
            "citations": citations,
            "plan": plan.model_dump(),
            "confidence": answer.confidence,
            "metadata": {
                "route": "rag_or_web",
                "web_enabled": payload.use_web,
                "web_results_count": len(web_results),
                "document_chunks_count": len(doc_chunks),
            },
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate an answer. Please try again.",
        ) from error


@router.get("/documents")
def documents(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Document).order_by(Document.created_at.desc()).all()

    return [
        {
            "id": row.id,
            "filename": row.original_filename,
            "file_type": row.file_type,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    try:
        VectorStore().delete_document(document_id)

        path = Path(document.path)

        db.delete(document)
        db.commit()

        if path.exists():
            path.unlink()

        return {
            "message": "Document deleted successfully.",
            "deleted_document_id": document_id,
        }

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Failed to delete document.",
        ) from error


@router.get("/history")
def history(db: Session = Depends(get_db)) -> list[dict]:
    return MemoryService().recent_history(db, limit=100)


@router.delete("/history")
def clear_history(db: Session = Depends(get_db)) -> dict:
    MemoryService().clear_history(db)

    return {
        "message": "Conversation history cleared successfully.",
    }


@router.post("/summarize")
def summarize(payload: SummarizeRequest, db: Session = Depends(get_db)) -> dict:
    document = db.query(Document).filter(Document.id == payload.document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    chunks = [
        {
            "id": chunk.id,
            "document_id": document.id,
            "chunk_index": chunk.chunk_index,
            "page": chunk.page,
            "text": chunk.text,
        }
        for chunk in document.chunks
    ]

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No content found for this document.",
        )

    return SummaryAgent().summarize(document.original_filename, chunks)
