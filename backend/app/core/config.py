from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Research Assistant"
    environment: Literal["development", "production"] = "development"

    database_url: str = "sqlite:///./storage/research_assistant.db"
    vector_db_dir: str = "./storage/vector_index"
    upload_dir: str = "./storage/uploads"

    llm_provider: Literal["groq", "openai", "gemini", "local"] = "groq"
    groq_api_key: str | None = None
    # Groq deprecated llama-3.3-70b-versatile for the free/developer tier with
    # shutdown scheduled for 2026-08-16. Keep the production default on a
    # production-listed model; Qwen 3.6 remains an opt-in Preview alternative.
    groq_model: str = "openai/gpt-oss-120b"
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
    allowed_file_extensions: Annotated[list[str], NoDecode] = [
        "pdf",
        "txt",
        "docx",
        "md",
    ]

    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    cors_origin_regex: str | None = r"https://.*\.vercel\.app"

    # ── Production hardening ──────────────────────────────────────────────────
    # When api_key is set, requests must send it in the api_key_header. Left
    # unset for local development (auth disabled).
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    # Account auth: signs the stateless session token that resolves a request to
    # a durable account principal. Set a strong secret in production; a stable
    # local default keeps dev working. TTL bounds how long a login stays valid.
    auth_secret: str | None = None
    auth_token_ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days
    # Paths that never require auth or rate limiting. Account auth endpoints are
    # public (you can't send an account token before you have one).
    public_paths: list[str] = [
        "/", "/health", "/ready", "/docs", "/redoc", "/openapi.json",
        "/auth/register", "/auth/login",
    ]

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
    # Workspace-scope quotas: counted separately from personal usage (the owner
    # key already isolates them) and independently tunable. Default to the
    # personal limits so behaviour is unchanged until an operator raises them for
    # a shared team workspace.
    workspace_max_pending_flows: int = 5
    workspace_execution_starts_per_window: int = 30
    workspace_artifact_generations_per_window: int = 20
    workspace_startup_validations_per_window: int = 20

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
    max_artifact_images: int = 6
    artifact_image_timeout_seconds: float = 5.0

    # ── Durable background execution (queue + worker) ──
    # When on, approved artifact generation is enqueued as a durable ExecutionJob
    # and run by the worker (`python -m app.worker`) instead of inline in the
    # request, so heavy work survives client disconnect. Off by default: the
    # inline path stays the tested default; the queue is the same code path, just
    # executed out-of-request. The DB-backed queue/state is always available.
    queue_artifacts: bool = False
    # Bounded retry for a failed job before it's recorded as honestly failed.
    job_max_attempts: int = 2
    # Worker poll interval when the queue is empty (seconds).
    worker_poll_seconds: float = 1.0

    # ── Queue scheduling policy (priority + concurrency classes + fairness) ──
    # When on, the queue claims by class priority (higher first) with created_at
    # FIFO tie-break, bounded by per-class concurrency caps and a per-owner
    # in-flight cap so no class or owner can monopolise workers. Off = plain FIFO.
    queue_scheduling_enabled: bool = True
    # Max jobs ONE owner may have running at once (fairness; >= 1).
    queue_per_owner_inflight_cap: int = 3
    # Per-class concurrency caps (0 = unbounded). Heavy classes are bounded
    # independently of light interactive work.
    queue_concurrency_interactive: int = 0
    queue_concurrency_artifact: int = 2
    queue_concurrency_validation: int = 1
    queue_concurrency_maintenance: int = 1

    # ── Operational SLO / alert policy (operator-only; never user-facing) ──
    # Durable-timestamp thresholds that classify stuck/degraded work. A job queued
    # longer than this (still not claimed) is "stuck". 0 disables the check.
    slo_enabled: bool = True
    slo_queued_seconds: int = 300
    # Running-too-long thresholds, per class (generation is legitimately slow, so
    # the artifact class gets a longer budget than light work). >= 0; 0 disables.
    slo_running_seconds_default: int = 120
    slo_running_seconds_artifact: int = 600
    slo_running_seconds_validation: int = 300
    slo_running_seconds_maintenance: int = 600
    # A cancel_requested job that doesn't reach canceled within this is "stuck".
    slo_cancel_seconds: int = 60
    # Queued count for one class above this is "backlog pressure". >= 1.
    slo_backlog_threshold: int = 20

    # ── External delivery (webhooks / alert routing; operator-only) ──
    # When on, curated observability events / alert-worthy policy results can be
    # POSTed to operator-configured webhook destinations. Delivery is durable and
    # best-effort around execution — a failed webhook can NEVER break a job.
    webhooks_enabled: bool = True
    # DELIVERY retry bound (separate from job retry / replay). >= 1.
    webhook_max_attempts: int = 4
    webhook_timeout_seconds: float = 5.0
    # Operator REDRIVE bound for terminal-failed deliveries (separate again from
    # auto-retry and from job retry/replay). >= 1.
    webhook_max_redrives: int = 3
    # Default suppression window (seconds) for repeated identical ALERT deliveries
    # to one destination — a persistent stuck job shouldn't re-deliver the same
    # critical alert every sweep. A severity change (escalation) is never
    # suppressed. Per-destination `suppress_seconds` overrides this. 0 = off.
    webhook_suppress_seconds: int = 300
    # A condition not detected for this long is a RESOLVED episode: the per-signal
    # occurrence counter resets, so repeated-condition escalation reflects a
    # currently-persisting problem, not stale history. >= 0.
    webhook_escalation_resolve_seconds: int = 1800
    # Destination health/cooldown: after this many CONSECUTIVE terminal delivery
    # failures a destination cools down (routing skips it) for `cooldown_seconds`,
    # so an unhealthy endpoint stops thrashing. Time-bounded + a success clears it;
    # never a permanent black hole. threshold >= 1; seconds >= 0 (0 disables).
    webhook_cooldown_threshold: int = 5
    webhook_cooldown_seconds: int = 600

    # ── Operator incident workflow (acknowledge / silence; operator-only) ──
    # Max bound for an operator silence so it is NEVER an infinite black hole; a
    # silenced incident still exists in operator state and auto-reopens on expiry.
    incident_max_silence_seconds: int = 86400  # 24h
    # Default silence duration the console offers. >= 1.
    incident_default_silence_seconds: int = 3600  # 1h

    # ── External incident sync (operator-only OUTBOUND export to incident tools) ──
    # Bounded per-record send retry and bounded operator redrive of failed syncs —
    # distinct from webhook delivery retry/redrive (incidents != event routing).
    incident_sync_max_attempts: int = 4
    incident_sync_max_redrives: int = 3
    # An external link with no successful sync within this window reads as "stale"
    # (bounded reconciliation — outbound stays primary; this only flags drift). >= 1.
    incident_link_stale_seconds: int = 86400  # 24h
    # Max links a single reconciliation sweep will recheck — bounded so a sweep
    # never spams external systems. >= 1.
    incident_reconcile_max_per_sweep: int = 25
    # Target readiness goes "stale" when its last successful check is older than this
    # window (evidence ages out → operator should revalidate). >= 1.
    incident_target_revalidate_seconds: int = 604800  # 7 days
    # Max targets a single scheduled revalidation sweep will recheck. >= 1.
    incident_revalidate_max_per_sweep: int = 10
    # Operator-only demo seed (Phase 6): populate a deterministic incident-sync
    # showcase in the `demo.aira-x.local` namespace so the platform is instantly
    # demonstrable. Operator-gated regardless; set False to disable in production.
    demo_seed_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "queue_concurrency_interactive", "queue_concurrency_artifact",
        "queue_concurrency_validation", "queue_concurrency_maintenance",
    )
    @classmethod
    def _validate_concurrency(cls, value):
        if int(value) < 0:
            raise ValueError("queue concurrency caps must be >= 0 (0 = unbounded)")
        return value

    @field_validator("queue_per_owner_inflight_cap")
    @classmethod
    def _validate_owner_cap(cls, value):
        if int(value) < 1:
            raise ValueError("queue_per_owner_inflight_cap must be >= 1")
        return value

    @field_validator(
        "slo_queued_seconds", "slo_running_seconds_default", "slo_running_seconds_artifact",
        "slo_running_seconds_validation", "slo_running_seconds_maintenance", "slo_cancel_seconds",
    )
    @classmethod
    def _validate_slo_seconds(cls, value):
        if int(value) < 0:
            raise ValueError("SLO thresholds (seconds) must be >= 0 (0 disables the check)")
        return value

    @field_validator("slo_backlog_threshold")
    @classmethod
    def _validate_backlog(cls, value):
        if int(value) < 1:
            raise ValueError("slo_backlog_threshold must be >= 1")
        return value

    @field_validator("webhook_max_attempts", "webhook_max_redrives")
    @classmethod
    def _validate_webhook_attempts(cls, value):
        if int(value) < 1:
            raise ValueError("webhook delivery/redrive bounds must be >= 1")
        return value

    @field_validator("webhook_suppress_seconds", "webhook_escalation_resolve_seconds",
                     "webhook_cooldown_seconds")
    @classmethod
    def _validate_webhook_suppress(cls, value):
        if int(value) < 0:
            raise ValueError("webhook suppression/resolve/cooldown windows must be >= 0 (0 disables)")
        return value

    @field_validator("webhook_cooldown_threshold")
    @classmethod
    def _validate_cooldown_threshold(cls, value):
        if int(value) < 1:
            raise ValueError("webhook_cooldown_threshold must be >= 1")
        return value

    @field_validator("incident_max_silence_seconds", "incident_default_silence_seconds")
    @classmethod
    def _validate_incident_silence(cls, value):
        if int(value) < 1:
            raise ValueError("incident silence durations must be >= 1")
        return value

    @field_validator("incident_sync_max_attempts", "incident_sync_max_redrives",
                     "incident_link_stale_seconds", "incident_reconcile_max_per_sweep",
                     "incident_target_revalidate_seconds", "incident_revalidate_max_per_sweep")
    @classmethod
    def _validate_incident_sync(cls, value):
        if int(value) < 1:
            raise ValueError("incident sync attempt/redrive/stale/reconcile/revalidate bounds must be >= 1")
        return value

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
        "workspace_max_pending_flows",
        "workspace_execution_starts_per_window",
        "workspace_artifact_generations_per_window",
        "workspace_startup_validations_per_window",
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

        if self.environment == "production":
            if not self.api_key:
                raise RuntimeError("API_KEY is required when ENVIRONMENT=production.")
            if not self.auth_secret:
                raise RuntimeError("AUTH_SECRET is required when ENVIRONMENT=production.")
            if self.cors_origin_regex:
                raise RuntimeError(
                    "CORS_ORIGIN_REGEX must be empty when ENVIRONMENT=production; "
                    "configure exact CORS_ORIGINS instead."
                )
            if not self.cors_origins:
                raise RuntimeError(
                    "At least one exact CORS_ORIGINS entry is required when "
                    "ENVIRONMENT=production."
                )
            if any(
                origin.startswith(("http://localhost", "http://127.0.0.1"))
                for origin in self.cors_origins
            ):
                raise RuntimeError(
                    "Localhost CORS_ORIGINS are not allowed when ENVIRONMENT=production."
                )


@lru_cache
def get_settings() -> Settings:
    value = Settings()
    value.ensure_storage()
    value.validate_runtime_config()
    return value


settings = get_settings()
