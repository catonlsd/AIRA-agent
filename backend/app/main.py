import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from app.api.routes import router
from app.core.config import settings
from app.db.database import init_db
from app.middleware import (
    APIKeyMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.routes.aira_x import router as aira_x_router
from app.routes.assistant import router as assistant_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("aira_x")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info(
        "AIRA-X API started (auth=%s, rate_limit=%s/min)",
        "on" if settings.api_key else "off",
        settings.rate_limit_per_minute if settings.rate_limit_enabled else "off",
    )
    yield


app = FastAPI(
    title="AIRA-X API",
    description=(
        "Unified AI research and execution API with conversational answers, "
        "document RAG, web research, workflow execution, approvals, memory, "
        "citations, and validation."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(aira_x_router)
app.include_router(assistant_router)
app.include_router(router)

# Middleware is added inner-first; the last added is outermost. Desired request
# flow: CORS -> logging -> security headers -> rate limit -> API key -> route.
app.add_middleware(APIKeyMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

_cors_kwargs = {
    "allow_origins": settings.cors_origins,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if settings.cors_origin_regex:
    _cors_kwargs["allow_origin_regex"] = settings.cors_origin_regex
app.add_middleware(CORSMiddleware, **_cors_kwargs)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to clients; log server-side instead.
    logger.exception("Unhandled error: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal server error."})


@app.get("/")
def root() -> dict:
    return {
        "message": "AIRA-X API is running",
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
    }


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up."""
    return {
        "status": "online",
        "service": "AIRA-X API",
        "version": "2.0.0",
    }


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: dependencies (DB, LLM config) are usable."""
    checks: dict[str, str] = {}

    try:
        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        finally:
            db.close()
    except Exception:
        checks["database"] = "error"

    provider = settings.llm_provider
    key = getattr(settings, f"{provider}_api_key", None) if provider != "local" else None
    checks["llm"] = "ok" if (provider == "local" or key) else "unconfigured"

    is_ready = checks["database"] == "ok"
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"ready": is_ready, "checks": checks},
    )
