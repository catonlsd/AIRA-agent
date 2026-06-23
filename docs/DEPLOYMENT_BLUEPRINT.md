# Deployment blueprint

A pragmatic path from "runs on my laptop" to "runs in production," in three escalating
tiers. **Documentation only** — no deployment code changes here; this complements the
hosting recipes in [DEPLOYMENT.md](DEPLOYMENT.md) and the persistence posture in
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

## Components to place

| Component | What it is | Stateless? | Scales by |
|---|---|---|---|
| **Backend (web)** | FastAPI app — user + operator APIs | yes | replicas behind a load balancer |
| **Worker** | thin drainer of the durable job/sync queue | yes (single is fine) | one is enough; add for throughput |
| **Frontend** | Next.js app (chat UI + operator console) | yes | replicas / CDN |
| **Database** | SQLite (local) → Postgres (prod) | — | managed Postgres |
| **Vector store** | ChromaDB (document Q&A) | — | volume or managed |
| **Object storage** | generated artifacts | — | bucket (prod) |
| **Secrets** | LLM key, `API_KEY`, signing secrets | — | platform secret manager |

The web and worker share **one** database. The worker is deliberately thin — it executes
queued work; it is not a second source of truth.

---

## Tier 1 — Single VM (simplest)

Good for a demo box, an evaluation environment, or a low-traffic deployment.

```
┌────────────────────── Ubuntu VM ──────────────────────┐
│  nginx (TLS, reverse proxy)                            │
│    ├── / ───────────► Next.js (next start, :3000)      │
│    └── /api ────────► uvicorn FastAPI (:8000)          │
│  systemd: aira-web (uvicorn) · aira-worker (worker)    │
│  Postgres (local or managed) · volume: chroma+artifacts│
│  cron/systemd-timer: POST /operator/deliveries/sweep   │
└────────────────────────────────────────────────────────┘
```

**Backend:** run `uvicorn app.main:app` under a `systemd` service; set `DATABASE_URL` to
Postgres, `API_KEY` to enforce the operator boundary, and the LLM provider key. Front it
with nginx for TLS.
**Worker:** a second `systemd` service running the queue worker against the same DB.
**Frontend:** `next build` then `next start` (or a static/standalone serve) behind nginx;
build with `NEXT_PUBLIC_API_URL` pointing at the public backend URL.
**Database:** managed Postgres preferred even on a single VM (backups + PITR for free).
**Secrets:** inject via the unit files' `EnvironmentFile=` from a root-only `.env`, or the
platform secret manager — never commit them.
**Scheduler:** a `systemd` timer or cron hitting the operator sweep so pending syncs
flush, links reconcile, and stale targets revalidate.

> Boot is self-healing: `create_all` + additive column migrations run idempotently, so a
> fresh VM with an empty Postgres comes up clean.

---

## Tier 2 — docker-compose (reproducible)

Good for staging, a portable demo, or a small production. Builds on the existing
`docker-compose.yml` (frontend + backend + `aira_storage` volume).

```
┌──────────────── docker-compose ────────────────┐
│  frontend  (Next.js standalone)  :3000          │
│  backend   (uvicorn FastAPI)     :8000          │
│  worker    (same image, worker command)         │
│  db        (postgres:16)         :5432          │
│  volumes: pgdata, chroma, artifacts             │
└─────────────────────────────────────────────────┘
```

- **One image, two roles:** the backend image runs the API in the `backend` service and
  the queue worker in a `worker` service (different command, same code/env).
- **Database:** add a `postgres` service (or point `DATABASE_URL` at managed Postgres) and
  a `pgdata` volume; drop the SQLite default.
- **Frontend:** `NEXT_PUBLIC_API_URL` is **build-time** — bake the browser-reachable
  backend URL when you build the image.
- **Secrets:** pass via the compose environment from a `.env` that is **not** committed
  (`.env` is git-ignored). No secrets are baked into images.
- **Scheduler:** a lightweight cron sidecar (or the host) calling the operator sweep.

This tier is the recommended default for showing AIRA-X to a customer: reproducible,
isolated, and one `docker compose up` away.

---

## Tier 3 — Kubernetes (future path)

Not implemented (and intentionally out of scope for the current phase), but the
architecture is already shaped for it. The mapping is direct:

| Concern | Kubernetes object |
|---|---|
| Backend (web) | `Deployment` (N replicas) + `Service` + `Ingress` |
| Worker | separate `Deployment` (1+), same image, worker command |
| Frontend | `Deployment` + `Service` (or a CDN/static host) |
| Database | managed Postgres (out of cluster) or an operator-managed `StatefulSet` |
| Vector store / artifacts | `PersistentVolumeClaim` or managed object storage |
| Secrets | `Secret` (sealed-secrets / external-secrets), mounted as env |
| Readiness / liveness | `readinessProbe: /ready`, `livenessProbe: /health` |
| Operator sweep | `CronJob` → `POST /operator/deliveries/sweep` |
| Config | `ConfigMap` for non-secret env |

Because the web tier is **stateless** and the worker is a thin, idempotent drainer, both
scale horizontally without coordination; `/ready` gates traffic until the DB + LLM config
are usable. The single env-var SQLite→Postgres seam means the only real production change
is pointing `DATABASE_URL` at managed Postgres.

---

## Cross-tier checklist

- [ ] `DATABASE_URL` → managed Postgres (not the SQLite default).
- [ ] `API_KEY` set → operator surface enforced.
- [ ] `DEMO_SEED_ENABLED=false` for a real production (leave on for demo/eval boxes).
- [ ] LLM provider key + model configured; `/ready` passes.
- [ ] Artifacts → durable object storage (not ephemeral container disk).
- [ ] Web and worker deployed as **separate** units against the same DB.
- [ ] Secrets via the platform secret manager; signing-secret column encrypted at rest.
- [ ] Operator sweep scheduled.
- [ ] TLS terminated at the proxy/ingress; explicit `CORS_ORIGINS`.

See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the full persistence/secret/
backup posture and [RELEASE_PROCESS.md](RELEASE_PROCESS.md) for cutting & rolling back a
release.
