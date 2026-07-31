# AIRA-X backend environment inventory

Status: authoritative for the Phase 3 internal-preview deployment preparation.
Source of truth: `backend/app/core/config.py` plus the four direct environment
lookups called out below. Variable names are case-insensitive in Pydantic, but
deployments must use the uppercase spellings in this document.

Do not commit a populated `.env`. `backend/.env.example` contains placeholders
only. Every environment change requires an API restart; settings are cached at
process import. A worker process must be restarted separately.

For the compact tables after “Release-critical variables,” these properties
apply to every listed row unless the row says otherwise: consumer is
`backend/app/core/config.py`; optional means omission uses the shown default;
secret is **no**; the safe placeholder is the shown default; development uses
the default; production uses the guidance column; missing-value validation is
the documented default/bound validator; and restart requirement is **API and
worker: yes**. This convention is part of the inventory, not an omission.

## Release-critical variables

| Variable | Consumer / purpose | Default | Required | Secret | Development | Production / missing behavior |
|---|---|---|---|---|---|---|
| `APP_NAME` | API display name | `AI Research Assistant` | No | No | Keep default | Optional; restart |
| `ENVIRONMENT` | Enables release-stage validation | `development` | Yes | No | `development` | `preview` or `production`; both fail closed on unsafe auth |
| `DATABASE_URL` | SQLAlchemy relational store | `sqlite:///./storage/research_assistant.db` | Yes | Credentials if remote | SQLite default | Initial preview: `sqlite:////app/storage/research_assistant.db`; a remote URL is unsupported until its driver and migrations are added |
| `VECTOR_DB_DIR` | Legacy JSON vector index | `./storage/vector_index` | Yes | No | Local storage | `/app/storage/vector_index`; startup creates it |
| `UPLOAD_DIR` | Original uploaded documents | `./storage/uploads` | Yes | User data | Local storage | `/app/storage/uploads`; startup creates it |
| `CHROMA_DIR` | Chroma persistent index | `./storage/chroma` | Yes | Derived user data | Local storage | `/app/storage/chroma`; startup creates it |
| `ARTIFACTS_DIR` | Generated DOCX/PPTX/XLSX outputs | `./storage/artifacts` | Yes | User data | Local storage | `/app/storage/artifacts`; startup creates it |
| `LLM_PROVIDER` | Selects provider | `groq` | Yes | No | `groq` or `local` | `groq`; unsupported value fails settings validation |
| `GROQ_API_KEY` | Groq authentication | none | When provider is Groq | Yes | Developer secret | Runtime secret; startup fails when absent |
| `GROQ_MODEL` | Groq chat-completion model | `openai/gpt-oss-120b` | Yes | No | Same default | Production-listed default; `qwen/qwen3.6-27b` is Preview and opt-in |
| `OPENAI_API_KEY` | OpenAI provider authentication | none | When provider is OpenAI | Yes | Optional | Startup fails when selected and absent |
| `OPENAI_MODEL` | OpenAI chat model | `gpt-4o-mini` | When provider is OpenAI | No | Optional | Restart after change |
| `GEMINI_API_KEY` | Gemini provider authentication | none | When provider is Gemini | Yes | Optional | Startup fails when selected and absent |
| `GEMINI_MODEL` | Gemini chat model | `gemini-1.5-flash` | When provider is Gemini | No | Optional | Verify independently before selecting |
| `WEB_SEARCH_PROVIDER` | Search adapter | `none` | Yes | No | `none` avoids network | `tavily` only when a key is provisioned; invalid choice fails validation |
| `TAVILY_API_KEY` | Tavily authentication | none | When provider is Tavily | Yes | Optional | Startup fails when selected and absent |
| `SERPAPI_API_KEY` | SerpAPI authentication | none | When provider is SerpAPI | Yes | Optional | Startup fails when selected and absent |
| `BRAVE_API_KEY` | Brave authentication | none | When provider is Brave | Yes | Optional | Startup fails when selected and absent |
| `API_KEY` | Explicit operator/service routes only | none | Preview/production | Yes | Server-side only | Strong random value; never expose to browser code |
| `API_KEY_HEADER` | Service-key header name | `X-API-Key` | Yes | No | Keep default | Coordinate any change with clients |
| `AUTH_SECRET` | Signs transitional account bearer tokens | local fallback | Preview/production | Yes | May be omitted locally | Distinct strong non-placeholder value |
| `AUTH_TOKEN_TTL_SECONDS` | Account token lifetime | `1209600` (14 days) | Yes | No | Default | Choose per access policy |
| `USER_AUTH_ENABLED` | Enables ordinary account authentication | `true` | Yes | No | Keep true | Must be true in preview/production |
| `ALLOW_ANONYMOUS_PROTECTED_ACCESS` | Local anonymous compatibility | `false` | Yes | No | Explicit opt-in only | Must be false |
| `DEVELOPMENT_AUTH_BYPASS` | Activates the explicit local bypass | `false` | Yes | No | Requires both local switches | Must be false |
| `PUBLIC_PATHS` | Routes exempt from auth/rate limit | built-in list | No | No | Default | Treat changes as a security review |
| `CORS_ORIGINS` | Exact browser origins, CSV | localhost origins | Yes | No | Localhost | Exact production frontend origin only |
| `CORS_ORIGIN_REGEX` | Additional browser-origin regex | all Vercel preview domains | No | No | Convenient locally | Set blank unless preview origins are intentionally allowed |
| `MAX_UPLOAD_SIZE_MB` | Streaming upload limit | `10` | Yes | No | Default | Align Nginx `client_max_body_size`; larger uploads return 413 |
| `ALLOWED_FILE_EXTENSIONS` | Accepted suffixes, CSV | `pdf,txt,docx,md` | Yes | No | Default | Restrict to parser-supported formats |
| `RATE_LIMIT_ENABLED` | In-process request limiter | `true` | Yes | No | `true` | Keep enabled; state is not shared across replicas |
| `RATE_LIMIT_PER_MINUTE` | Per-client fixed-window limit | `60` | Yes | No | Default | Tune after observing internal preview |
| `LOGIN_FAILURE_LIMIT` | Failed logins allowed per local window | `5` | Yes | No | Default | Process-local; replace with shared limiter for external beta |
| `LOGIN_FAILURE_WINDOW_SECONDS` | Failed-login window | `300` | Yes | No | Default | Process-local |
| `SECURITY_HEADERS_ENABLED` | Response hardening headers | `true` | Yes | No | `true` | Must remain true |
| `REQUEST_LOGGING_ENABLED` | Structured request log | `true` | Yes | No | `true` | Must remain true; stdout is collected by Docker/systemd |

## Retrieval and artifact variables

| Variable | Purpose | Default | Production guidance / missing behavior |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | Embedding backend | `sentence_transformers` | Use the default; first startup may be slow while the local model loads |
| `EMBEDDING_MODEL` | Local embedding model | `all-MiniLM-L6-v2` | Changing it requires a full vector reindex |
| `OPENAI_EMBEDDING_MODEL` | Reserved OpenAI embedding model | `text-embedding-3-small` | Not used by the current provider implementation |
| `VECTOR_STORE` | Vector-store selection | `chroma` | Keep `chroma`; JSON remains a legacy parallel index |
| `DOCUMENT_COLLECTION` | Chroma collection name | `aira_documents` | Changing it makes the old collection invisible until reindexed |
| `CHUNK_SIZE` | Ingestion chunk characters | `1000` | Changing it requires reindexing |
| `CHUNK_OVERLAP` | Ingestion overlap | `150` | Must remain smaller than chunk size; changing it requires reindexing |
| `RETRIEVAL_K` | Final retrieved chunk count | `6` | Tune through evaluation, not production guesswork |
| `RERANK_CANDIDATE_K` | Candidate pool before reranking | `12` | Keep at least `RETRIEVAL_K` |
| `MEMORY_LIMIT` | Recent chat turns used | `10` | Tune only with token-budget evidence |
| `ARTIFACT_RESEARCH_GROUNDING` | Permits web grounding for artifacts | `true` | Disable until web-search production smoke tests pass |
| `ENABLE_ARTIFACT_IMAGES` | Permits remote image sourcing | `true` | Disable for the initial preview unless explicitly evaluated |
| `ARTIFACT_IMAGE_PROVIDER` | Image source adapter | `openverse` | `none` disables |
| `MAX_ARTIFACT_IMAGES` | Per-artifact image bound | `6` | Keep bounded |
| `ARTIFACT_IMAGE_TIMEOUT_SECONDS` | Remote image timeout | `5.0` | Keep bounded |

## Execution, quota, and validation variables

These are all consumed by `Settings` in `backend/app/core/config.py`. They are
non-secret, use the listed defaults when absent, reject invalid bounds during
settings validation where noted, and require an API/worker restart to change.

| Variable | Default | Purpose / production guidance |
|---|---:|---|
| `QUOTAS_ENABLED` | `true` | Per-principal quota enforcement; keep enabled |
| `QUOTA_WINDOW_SECONDS` | `3600` | Quota window; must be positive |
| `MAX_PENDING_FLOWS_PER_OWNER` | `5` | Personal pending-flow cap; positive |
| `EXECUTION_STARTS_PER_WINDOW` | `30` | Personal execution cap; positive |
| `ARTIFACT_GENERATIONS_PER_WINDOW` | `20` | Personal artifact cap; positive |
| `STARTUP_VALIDATIONS_PER_WINDOW` | `20` | Personal validation cap; positive |
| `WORKSPACE_MAX_PENDING_FLOWS` | `5` | Workspace pending-flow cap; positive |
| `WORKSPACE_EXECUTION_STARTS_PER_WINDOW` | `30` | Workspace execution cap; positive |
| `WORKSPACE_ARTIFACT_GENERATIONS_PER_WINDOW` | `20` | Workspace artifact cap; positive |
| `WORKSPACE_STARTUP_VALIDATIONS_PER_WINDOW` | `20` | Workspace validation cap; positive |
| `ENABLE_BOOT_VALIDATION` | `true` | Allows bounded generated-app subprocess boots |
| `BOOT_READY_TIMEOUT_SECONDS` | `8.0` | Generated-app readiness timeout |
| `ENABLE_DOCKER_VALIDATION` | `false` | Keep false on the initial host unless nested Docker is deliberately allowed |
| `QUEUE_ARTIFACTS` | `false` | Keep false for the SQLite internal preview; no separate worker required |
| `JOB_MAX_ATTEMPTS` | `2` | Durable job retry bound |
| `WORKER_POLL_SECONDS` | `1.0` | Worker idle poll interval |
| `QUEUE_SCHEDULING_ENABLED` | `true` | Priority/fairness scheduling |
| `QUEUE_PER_OWNER_INFLIGHT_CAP` | `3` | Must be at least one |
| `QUEUE_CONCURRENCY_INTERACTIVE` | `0` | Zero means unbounded |
| `QUEUE_CONCURRENCY_ARTIFACT` | `2` | Artifact concurrency cap |
| `QUEUE_CONCURRENCY_VALIDATION` | `1` | Validation concurrency cap |
| `QUEUE_CONCURRENCY_MAINTENANCE` | `1` | Maintenance concurrency cap |

## Operations and incident variables

| Variable | Default | Purpose / missing behavior |
|---|---:|---|
| `SLO_ENABLED` | `true` | Enables operational classifications |
| `SLO_QUEUED_SECONDS` | `300` | Queued-stuck threshold; zero disables |
| `SLO_RUNNING_SECONDS_DEFAULT` | `120` | Default running threshold; zero disables |
| `SLO_RUNNING_SECONDS_ARTIFACT` | `600` | Artifact running threshold |
| `SLO_RUNNING_SECONDS_VALIDATION` | `300` | Validation running threshold |
| `SLO_RUNNING_SECONDS_MAINTENANCE` | `600` | Maintenance running threshold |
| `SLO_CANCEL_SECONDS` | `60` | Cancel-stuck threshold |
| `SLO_BACKLOG_THRESHOLD` | `20` | Backlog threshold; must be positive |
| `WEBHOOKS_ENABLED` | `true` | Enables configured outbound destinations; no destination means no delivery |
| `WEBHOOK_MAX_ATTEMPTS` | `4` | Delivery retry bound; positive |
| `WEBHOOK_TIMEOUT_SECONDS` | `5.0` | Outbound timeout |
| `WEBHOOK_MAX_REDRIVES` | `3` | Operator redrive bound; positive |
| `WEBHOOK_SUPPRESS_SECONDS` | `300` | Duplicate-alert suppression; zero disables |
| `WEBHOOK_ESCALATION_RESOLVE_SECONDS` | `1800` | Episode reset window |
| `WEBHOOK_COOLDOWN_THRESHOLD` | `5` | Consecutive-failure threshold; positive |
| `WEBHOOK_COOLDOWN_SECONDS` | `600` | Destination cooldown; zero disables |
| `INCIDENT_MAX_SILENCE_SECONDS` | `86400` | Maximum bounded silence; positive |
| `INCIDENT_DEFAULT_SILENCE_SECONDS` | `3600` | Default silence; positive |
| `INCIDENT_SYNC_MAX_ATTEMPTS` | `4` | External incident retry bound |
| `INCIDENT_SYNC_MAX_REDRIVES` | `3` | External incident redrive bound |
| `INCIDENT_LINK_STALE_SECONDS` | `86400` | External-link stale threshold |
| `INCIDENT_RECONCILE_MAX_PER_SWEEP` | `25` | Reconciliation batch bound |
| `INCIDENT_TARGET_REVALIDATE_SECONDS` | `604800` | Target evidence max age |
| `INCIDENT_REVALIDATE_MAX_PER_SWEEP` | `10` | Revalidation batch bound |
| `DEMO_SEED_ENABLED` | `true` | Set `false` in production |

## Direct environment lookups and process settings

| Variable | Consumer | Default | Guidance |
|---|---|---|---|
| `AIRA_EMBEDDING_PROVIDER` | `rag/embedding_provider.py` | falls back to `EMBEDDING_PROVIDER` | Compatibility override; prefer the canonical setting |
| `AIRA_CHROMA_DIR` | `services/vector_store_service.py` | falls back to `CHROMA_DIR` | Compatibility override; if present it wins |
| `AIRA_ASSISTANT_SUPERVISOR` | `routes/assistant.py` | disabled unless truthy | Set `1` for the supervisor route; restart |
| `AIRA_TRACE_LOG` | `trace_service.py` | `storage/traces.jsonl` | Place on the persistent volume; contains user-derived operational data |
| `NEXT_PUBLIC_API_URL` | Frontend build | localhost API | Build-time, public, never a secret; Vercel change is outside Phase 3 |

`HOST`, `PORT`, `WEB_CONCURRENCY`, and graceful-shutdown timeout are not consumed
as application environment variables today. The checked-in Docker command is
one Uvicorn process on `0.0.0.0:8000`; Nginx binds externally. Do not claim these
variables work without first adding and testing an entrypoint.

## Deployment-facing settings that do not exist

These names are documentation-only placeholders and must **not** be added to a
host env file expecting behavior. Each is non-secret, ignored when present, and
would require a code/config change plus restart to become effective.

| Proposed variable | Current consumer | Purpose | Required | Current default | Dev recommendation | Production recommendation | Secret | Safe example | Missing behavior | Restart |
|---|---|---|---|---|---|---|---|---|---|---|
| `HOST` | none; Docker CMD | Bind address | No | fixed `0.0.0.0` | fixed command | Keep backend on loopback/container network | No | `127.0.0.1` | Ignored | Would require API restart |
| `PORT` | none; Docker CMD | API port | No | fixed `8000` | `8000` | Nginx proxies to 8000 | No | `8000` | Ignored | Would require API restart |
| `WEB_CONCURRENCY` | none | API workers | No | one | one | one for SQLite preview | No | `1` | Ignored | Would require API restart |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | none | Drain timeout | No | Uvicorn default / Compose 45s stop grace | default | Configure at process supervisor if needed | No | `30` | Ignored | Would require API restart |
| `TRUSTED_HOSTS` | none | Host-header allowlist | No | no TrustedHost middleware | localhost | Gap: enforce at Nginx now; add middleware before public beta | No | `aira-x.example.com` | Ignored | Would require API restart |
| `REQUEST_BODY_LIMIT_MB` | none | General body bound | No | route/framework defaults | default | Gap: Nginx bounds body; upload route separately enforces its limit | No | `11` | Ignored | Would require API restart |
| `STREAM_TIMEOUT_SECONDS` | none | SSE duration | No | application/transport defaults | default | Nginx example uses 3600 seconds | No | `3600` | Ignored | Proxy reload if proxy-only |
| `TRUST_PROXY_HEADERS` | none | Forwarded-header trust | No | Uvicorn defaults | default | Nginx is local; explicitly configure before a multi-hop proxy | No | `true` | Ignored | Would require API restart |

Public/backend base URL is `NEXT_PUBLIC_API_URL`, consumed at frontend **build**
time. The backend has no public-base-URL setting. Streaming buffering and timeout
are reverse-proxy configuration in the checked-in Nginx example, not backend
environment variables.

## Secret rotation

1. Create a new provider key or application secret in its owning system.
2. Replace the runtime secret on the host without writing it to Git or logs.
3. Restart API and worker processes.
4. Verify `/ready`, then a narrow authenticated smoke test.
5. Revoke the old secret only after verification. Rotating `AUTH_SECRET`
   invalidates all existing account tokens; communicate that logout event.
