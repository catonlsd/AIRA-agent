import logging
import os
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
from app.routes.activity import router as activity_router
from app.routes.auth import router as auth_router
from app.routes.operator import router as operator_router
from app.routes.preferences import router as preferences_router
from app.routes.resources import router as resources_router
from app.routes.bundles import router as bundles_router
from app.routes.chat_context import router as chat_context_router
from app.routes.jobs import router as jobs_router
from app.routes.runs import router as runs_router
from app.routes.search import router as search_router
from app.routes.workspaces import router as workspaces_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("aira_x")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Register the safe, optional artifact image provider (Openverse, guarded).
    # Tests keep AIRA_ENABLE_ARTIFACT_IMAGES off, so this stays a no-op there.
    try:
        from app.artifacts.image_providers import build_default_provider
        from app.artifacts.images import set_image_provider

        set_image_provider(build_default_provider())
    except Exception:
        pass
    # Register durable-queue job handlers so an enqueued artifact job can run
    # (in-process drain, or out-of-process via `python -m app.worker`).
    try:
        from app.job_handlers import register_default_handlers

        register_default_handlers()
    except Exception:
        pass
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

app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(operator_router)
app.include_router(resources_router)
app.include_router(runs_router)
app.include_router(search_router)
app.include_router(chat_context_router)
app.include_router(bundles_router)
app.include_router(jobs_router)
app.include_router(activity_router)
app.include_router(aira_x_router)
app.include_router(assistant_router)
app.include_router(preferences_router)
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


@app.get("/artifacts/{owner}/{filename}")
def download_artifact(owner: str, filename: str, request: Request):
    """Serve a generated artifact, scoped to the owning principal.

    Access is enforced at the route, not by an unguessable filename: each owner
    has an isolated directory keyed by an opaque HMAC token, so cross-owner
    filename guessing fails. When API-key auth is enabled, an authenticated
    request must additionally match the owner. Path traversal is blocked.
    """
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    from app.auth import (
        accessible_owner_tokens,
        principal_from_request,
        resolve_account_principal,
    )

    # Reject any path-segment tampering up front.
    if "/" in owner or "\\" in owner or ".." in owner or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    # An authenticated account may reach its own personal scope OR any workspace
    # it belongs to (scope-aware). Cross-scope access is denied, regardless of
    # the api-key gate.
    account = resolve_account_principal(request)
    if account is not None and owner not in accessible_owner_tokens(account.account_id):
        logger.info('{"event": "artifact_access_denied", "owner": "%s"}', owner)
        raise HTTPException(status_code=404, detail="Artifact not found.")
    if settings.api_key and account is None:
        principal = principal_from_request(request)
        if principal.authenticated and principal.owner_token != owner:
            logger.info('{"event": "artifact_access_denied", "owner": "%s"}', owner)
            raise HTTPException(status_code=404, detail="Artifact not found.")

    root = Path(settings.artifacts_dir).resolve()
    owner_dir = (root / owner).resolve()
    target = (owner_dir / filename).resolve()
    # Isolation guard: the file must live directly inside this owner's directory.
    if owner_dir.parent != root or target.parent != owner_dir or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
    )


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
    """Readiness: local dependencies and required provider config are usable.

    This deliberately does not make a paid/provider network call. Deployment
    smoke tests must verify upstream connectivity separately.
    """
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
    checks["llm"] = "configured" if (provider == "local" or key) else "unconfigured"

    storage_paths = (
        settings.vector_db_dir,
        settings.upload_dir,
        settings.chroma_dir,
        settings.artifacts_dir,
    )
    checks["storage"] = (
        "ok"
        if all(Path(path).is_dir() and os.access(path, os.W_OK) for path in storage_paths)
        else "error"
    )

    is_ready = (
        checks["database"] == "ok"
        and checks["llm"] == "configured"
        and checks["storage"] == "ok"
    )
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"ready": is_ready, "checks": checks},
    )
