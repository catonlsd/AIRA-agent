# AIRA-X Deployment Guide

Covers Render, Railway, VPS (Ubuntu), Docker, and Kubernetes-readiness.

> The backend depends on `torch`/`sentence-transformers`/`chromadb`, so the image
> and memory footprint are non-trivial (~2–4 GB image, ~1–2 GB RAM). To run lean,
> set `EMBEDDING_PROVIDER=hashing` (keyword embeddings, no model download) at the
> cost of semantic document search quality.

Required env (all targets): `LLM_PROVIDER` + the matching key (e.g.
`GROQ_API_KEY`). Recommended for any public deploy: `API_KEY`, explicit
`CORS_ORIGINS`. Frontend needs `NEXT_PUBLIC_API_URL` (browser-reachable) at build.

---

## 1. Render

**Backend (Web Service, Docker or native):**
- Native: Build `pip install -r backend/requirements.txt` · Start
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (root dir `backend`).
- Docker: point at `backend/Dockerfile`.
- Health check path: `/health`. Add a persistent disk mounted at
  `backend/storage` (SQLite + Chroma + uploads).
- Env: `LLM_PROVIDER`, `GROQ_API_KEY`, `API_KEY`, `CORS_ORIGINS`.
- **Caveat:** free tier has limited RAM/disk — sentence-transformers may OOM; use
  `EMBEDDING_PROVIDER=hashing` or a paid instance. Ephemeral disk loses Chroma
  data without a persistent disk.

**Frontend (Web Service / Static via Docker):**
- Build `npm ci && npm run build`, Start `npm run start` (root dir `frontend`),
  or use `frontend/Dockerfile`.
- Build env: `NEXT_PUBLIC_API_URL=https://<backend>.onrender.com`.

---

## 2. Railway

- Two services from the monorepo (backend root `backend`, frontend root `frontend`).
- Backend start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Frontend: build `npm ci && npm run build`, start `npm run start`; set
  `NEXT_PUBLIC_API_URL` to the backend's public URL (build-time variable).
- Add a Volume on the backend mounted at `/app/storage` (or `backend/storage`).
- **Caveat:** set the build-time `NEXT_PUBLIC_API_URL` before the frontend build;
  changing it later requires a rebuild.

---

## 3. VPS (Ubuntu)

```bash
# Backend
sudo apt update && sudo apt install -y python3.12 python3.12-venv
cd /opt/aira/backend && python3.12 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set keys, API_KEY, CORS_ORIGINS
# Run under a process manager (systemd example):
#   ExecStart=/opt/aira/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
```
```bash
# Frontend
cd /opt/aira/frontend && npm ci
NEXT_PUBLIC_API_URL=https://api.example.com npm run build
npm run start   # or run the standalone server: node .next/standalone/server.js
```
- Put **nginx** in front for TLS + reverse proxy. **Important for streaming:**
  disable proxy buffering on the SSE route so tokens flush:
  ```nginx
  location /aira-x/stream { proxy_pass http://127.0.0.1:8000; proxy_buffering off; proxy_read_timeout 300s; }
  ```
- **Caveat:** without `proxy_buffering off`, SSE streaming will appear to "wait
  for the full answer".

---

## 4. Docker

```bash
cp backend/.env.example backend/.env   # set keys
NEXT_PUBLIC_API_URL=http://localhost:8000 docker compose up --build
```
- Persistent data: the `aira_storage` named volume (`/app/storage`).
- Production: set `NEXT_PUBLIC_API_URL` to the public backend URL, set `API_KEY`,
  and restrict `CORS_ORIGINS`. Build/run the two images independently if you
  deploy them on separate hosts.
- **Caveat:** the backend image is large (torch). First boot is slow while the
  embedding model downloads (cache the volume / bake the model for faster starts).

---

## 5. Kubernetes readiness

Not shipped (no manifests), but the app is K8s-friendly:
- **Probes:** `livenessProbe` → `GET /health`; `readinessProbe` → `GET /ready`.
- **Config:** env via ConfigMap; secrets (`GROQ_API_KEY`, `API_KEY`) via Secret.
- **State:** `storage/` (SQLite + Chroma) needs a PVC — or migrate to Postgres +
  a hosted/standalone vector store for true horizontal scaling (SQLite + local
  Chroma are single-node). The embedding + vector-store interfaces are swappable
  to support this later.
- **Scaling caveat:** conversation memory on `/assistant` is currently global
  (single DB) and not session-scoped; rate limiting is in-memory per replica.
  Address both before scaling beyond one backend replica.
