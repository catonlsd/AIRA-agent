from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Research Assistant"
    environment: Literal["development", "production"] = "development"

    database_url: str = "sqlite:///./storage/research_assistant.db"
    vector_db_dir: str = "./storage/vector_index"
    upload_dir: str = "./storage/uploads"

    llm_provider: Literal["groq", "openai", "gemini", "local"] = "groq"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    # Swappable embedding backend. "sentence_transformers" = local semantic model;
    # "hashing" = dependency-free fallback (used in tests/CI). Overridable per
    # process via the AIRA_EMBEDDING_PROVIDER env var.
    embedding_provider: Literal["sentence_transformers", "hashing", "local"] = "sentence_transformers"
    embedding_model: str = "all-MiniLM-L6-v2"
    openai_embedding_model: str = "text-embedding-3-small"

    # Swappable vector store. "chroma" = ChromaDB (default). Overridable via env.
    vector_store: Literal["chroma", "json"] = "chroma"
    chroma_dir: str = "./storage/chroma"
    document_collection: str = "aira_documents"
    # Safe default output area for generated artifacts (PPTX/DOCX/XLSX).
    artifacts_dir: str = "./storage/artifacts"

    web_search_provider: Literal["tavily", "serpapi", "brave", "none"] = "none"
    tavily_api_key: str | None = None
    serpapi_api_key: str | None = None
    brave_api_key: str | None = None

    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_k: int = 6
    # Pull a wider candidate pool from the vector store, then rerank + dedupe down
    # to retrieval_k before answer composition (better evidence, same final size).
    rerank_candidate_k: int = 12
    memory_limit: int = 10

    max_upload_size_mb: int = 10
    allowed_file_extensions: list[str] = ["pdf", "txt", "docx", "md"]

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    cors_origin_regex: str | None = r"https://.*\.vercel\.app"

    # ── Production hardening ──────────────────────────────────────────────────
    # When api_key is set, requests must send it in the api_key_header. Left
    # unset for local development (auth disabled).
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    # Paths that never require auth or rate limiting.
    public_paths: list[str] = ["/", "/health", "/ready", "/docs", "/redoc", "/openapi.json"]

    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    security_headers_enabled: bool = True
    request_logging_enabled: bool = True

    # ── Per-principal usage quotas (multi-user fairness / abuse resistance) ──
    # Operator-tunable; durable + multi-process-safe. Disable for trusted setups.
    quotas_enabled: bool = True
    quota_window_seconds: int = 3600
    max_pending_flows_per_owner: int = 5
    execution_starts_per_window: int = 30
    artifact_generations_per_window: int = 20
    startup_validations_per_window: int = 20

    # Boot/health validation actually launches a generated app in a bounded
    # subprocess. Operators can disable it in constrained environments (no spawn
    # permission, locked-down CI) — detection still runs and reports honestly.
    enable_boot_validation: bool = True
    boot_ready_timeout_seconds: float = 8.0
    # Docker/compose live-boot validation is OFF by default: spinning up
    # containers is heavy and environment-dependent. When disabled (or Docker is
    # absent) Docker targets are detected and reported as an honest skip, never
    # faked as "validated". Turn on only where a bounded local Docker boot is safe.
    enable_docker_validation: bool = False

    # ── Artifact enrichment (content depth + web grounding + images) ──
    # Ground artifact content in a bounded web-research pass when there are no
    # uploaded documents, so decks/reports carry real substance, not stubs.
    artifact_research_grounding: bool = True
    # Optional, safe image sourcing for artifacts. Off-by-default in tests (set
    # via env) but on for the running app. Uses CC-licensed Openverse results,
    # bounded and fully guarded — generation never depends on or fails for images.
    enable_artifact_images: bool = True
    artifact_image_provider: str = "openverse"   # openverse | none
    max_artifact_images: int = 4
    artifact_image_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("allowed_file_extensions", mode="before")
    @classmethod
    def parse_allowed_file_extensions(cls, value):
        if isinstance(value, str):
            return [ext.strip().lower().replace(".", "") for ext in value.split(",") if ext.strip()]
        return value

    @field_validator(
        "quota_window_seconds",
        "max_pending_flows_per_owner",
        "execution_starts_per_window",
        "artifact_generations_per_window",
        "startup_validations_per_window",
    )
    @classmethod
    def _positive_quota(cls, value, info):
        # Quota limits must be positive integers — fail clearly on misconfig.
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer (got {value!r}).")
        return value

    def ensure_storage(self) -> None:
        Path("./storage").mkdir(parents=True, exist_ok=True)
        Path(self.vector_db_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)
        Path(self.artifacts_dir).mkdir(parents=True, exist_ok=True)

    def validate_runtime_config(self) -> None:
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq.")

        if self.llm_provider == "openai" and not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")

        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini.")

        if self.web_search_provider == "tavily" and not self.tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is required when WEB_SEARCH_PROVIDER=tavily.")

        if self.web_search_provider == "serpapi" and not self.serpapi_api_key:
            raise RuntimeError("SERPAPI_API_KEY is required when WEB_SEARCH_PROVIDER=serpapi.")

        if self.web_search_provider == "brave" and not self.brave_api_key:
            raise RuntimeError("BRAVE_API_KEY is required when WEB_SEARCH_PROVIDER=brave.")


@lru_cache
def get_settings() -> Settings:
    value = Settings()
    value.ensure_storage()
    value.validate_runtime_config()
    return value


settings = get_settings()