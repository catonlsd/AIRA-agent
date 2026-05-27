from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from app.api.routes import router
from app.core.config import settings
from app.db.database import init_db
from app.routes.aira_x import router as aira_x_router
from app.routes.assistant import router as assistant_router


app = FastAPI(
    title="AIRA-X API",
    description=(
        "Unified AI research and execution API with conversational answers, "
        "document RAG, web research, workflow execution, approvals, memory, "
        "citations, and validation."
    ),
    version="2.0.0",
)

app.include_router(aira_x_router)
app.include_router(assistant_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ai-research-assistant-catonlsds-projects.vercel.app",
        "https://ai-research-assistant-lime-five.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root() -> dict:
    return {
        "message": "AIRA-X API is running",
        "docs": "/docs",
        "health": "/health",
        "assistant": "/assistant/run",
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "online",
        "service": "AIRA-X API",
        "version": "2.0.0",
    }


app.include_router(router)
