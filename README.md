# AIRA-X

**AIRA-X** is a unified conversational AI assistant: one supervisor orchestrates
chat, web research, document Q&A, and safe task execution behind a single
streaming API and a Next.js chat UI.

- 🧠 **One supervisor, one brain** — every turn is classified and routed by a
  single `AssistantSupervisor`; the research and execution stacks are
  *capabilities*, not separate apps.
- 💬 **Streaming chat** — token-by-token SSE responses.
- 📄 **Document-first Q&A** — upload PDFs/DOCX/TXT/MD, ask grounded questions
  with citations (ChromaDB + local embeddings), honest "not in your files".
- 🔎 **Web research** — source-grounded answers when a query needs current info.
- ⚙️ **Safe execution** — file/git/shell/python tools with approval gating.
- 🧾 **Tracing** — every turn persisted (route, latency, sources, status).
- 🔐 **Production hardening** — API-key auth, rate limiting, security headers,
  readiness checks, structured logging, clean error handling.

---

## Architecture

```
Browser (Next.js chat)
   │  POST /aira-x/stream  (SSE)   ·   POST /assistant/run  (non-streaming)
   ▼
FastAPI routes  ──►  AssistantSupervisor
                         │  build context → classify (hybrid router) → dispatch
                         ├── general_chat / self_memory ─► LLM (streamed)
                         ├── web_research ─────────────► ResearchService
                         ├── document_qa ──────────────► DocumentQnAService ─► ChromaDB
                         ├── execution / artifact ─────► ExecutionService ─► LangGraph workflow + tools
                         └── compose → TraceService (JSONL)
```

| Concern | Module |
|---|---|
| Orchestration | `backend/app/assistant_supervisor.py` |
| Intent routing | `backend/app/turn_classifier.py`, `backend/app/intent_router.py` |
| Response contract | `backend/app/schemas/assistant_response.py`, `response_composer.py` |
| Turn context / memory | `backend/app/context_builder.py` |
| Research capability | `backend/app/capabilities/research/` |
| Execution capability | `backend/app/capabilities/execution/` + `backend/graph/`, `backend/agents/`, `backend/tools/` |
| Document Q&A + vectors | `backend/app/services/document_qa_service.py`, `vector_store_service.py`, `app/rag/` |
| Tracing | `backend/app/services/trace_service.py` |
| Hardening middleware | `backend/app/middleware.py` |

## Tech stack

- **Backend:** Python 3.12, FastAPI, LangGraph, ChromaDB, sentence-transformers, SQLAlchemy (SQLite), Groq/OpenAI/Gemini LLMs.
- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind.

---

## Quickstart (local)

### Prerequisites
- Python 3.12, Node 20+ (22 recommended), an LLM API key (Groq by default).

### 1. Backend
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate   |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```
Backend runs at `http://localhost:8000` (`/health`, `/ready`, `/docs`).

### 2. Frontend
```bash
cd frontend
npm install
# Point the UI at the backend (defaults to http://localhost:8000):
# echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```
UI runs at `http://localhost:3000`.

See **[HOW_TO_USE.md](HOW_TO_USE.md)** for a full walkthrough.

---

## Docker

```bash
cp backend/.env.example backend/.env   # fill GROQ_API_KEY
docker compose up --build
```
- Frontend → `http://localhost:3000`
- Backend  → `http://localhost:8000`
- Persistent data (SQLite, Chroma, uploads, traces) lives in the `aira_storage` volume.

> `NEXT_PUBLIC_API_URL` is baked at build time. For non-local deploys, set it to a
> browser-reachable backend URL: `NEXT_PUBLIC_API_URL=https://api.example.com docker compose build`.

Images: backend (`backend/Dockerfile`), frontend (`frontend/Dockerfile`, Next.js
standalone). No secrets are baked into images — they come from the environment.

---

## Environment variables

Full reference: **[backend/.env.example](backend/.env.example)**. Key ones:

| Variable | Purpose | Required? | Default |
|---|---|---|---|
| `LLM_PROVIDER` | `groq` / `openai` / `gemini` / `local` | yes | `groq` |
| `GROQ_API_KEY` | Groq key (if provider=groq) | yes* | — |
| `EMBEDDING_PROVIDER` | `sentence_transformers` / `hashing` | no | `sentence_transformers` |
| `VECTOR_STORE` / `CHROMA_DIR` | vector store + data dir | no | `chroma` / `./storage/chroma` |
| `DATABASE_URL` | SQLAlchemy URL | no | `sqlite:///./storage/research_assistant.db` |
| `API_KEY` / `API_KEY_HEADER` | enable API-key auth | no | unset (auth off) |
| `RATE_LIMIT_PER_MINUTE` | per-client limit | no | `60` |
| `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | allowed origins | no | localhost + `*.vercel.app` |
| `NEXT_PUBLIC_API_URL` (frontend) | backend URL for the browser | yes (deploy) | `http://localhost:8000` |

\* required for whichever provider is selected.

---

## Deployment

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for Render, Railway, VPS (Ubuntu),
Docker, and Kubernetes-readiness guidance.

---

## Testing

```bash
cd backend && python -m pytest        # full backend suite
cd frontend && npm run lint && npm run build
```

---

## Security & ops

- **Auth:** `API_KEY` enables `X-API-Key` enforcement (off by default; suited to
  server-to-server — a public browser SPA needs session auth instead).
- **Rate limiting**, **security headers**, **CORS**, **/ready** readiness, and a
  **global JSON error handler** (no stack-trace leaks) are built in.
- **Tracing:** per-turn JSONL at `storage/traces.jsonl` (rotates at 5 MB);
  inspect recent turns via `GET /aira-x/traces`.

## Project status

Phase 1 (unified supervisor, streaming, ChromaDB, hardening) is complete.
See [docs/PHASE1_VALIDATION_REPORT.md](docs/PHASE1_VALIDATION_REPORT.md) and
[docs/PRODUCTION_READINESS_REPORT.md](docs/PRODUCTION_READINESS_REPORT.md).
