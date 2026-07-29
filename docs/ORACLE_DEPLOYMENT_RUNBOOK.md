# Oracle Cloud deployment runbook — preparation only

This runbook is a reviewed execution plan. Phase 3 does **not** authorize running
it against Oracle Cloud, changing DNS/CORS/Vercel, or making paid provider calls.

## Immediate attention before deployment

1. Provision/confirm a Groq key and verify `openai/gpt-oss-120b` against AIRA-X
   chat, streaming, RAG, and web-search prompts in a separately authorized smoke
   test. Repository tests use mocks and prove no provider compatibility.
2. Complete a backup/restore drill. No automated dual-index rebuild command
   exists yet.
3. Decide the exact production frontend origin. Production must replace the
   permissive Vercel preview regex with the approved origin.
4. Resolve the frontend/service-key delivery design before external beta. A
   browser must not contain a privileged long-lived `API_KEY`.

## Topology

```text
Internet -> Oracle firewall (80/443 only) -> Nginx TLS
  -> 127.0.0.1:3000 frontend
  -> 127.0.0.1:8000 FastAPI
       -> /srv/aira-x/storage (SQLite, uploads, artifacts, both indexes)
       -> Groq / Tavily over outbound HTTPS
```

## Resource recommendation

Prefer the Oracle region closest to intended users that has the selected shape
and block-volume capacity available. Keep application and volume in the same
availability domain where the shape requires it. Confirm service limits,
egress pricing, backup policy, and data-residency requirements before selection.

| Stage | Compute | Boot disk | Data disk | Process topology |
|---|---|---:|---:|---|
| Minimum internal-preview experiment | 2 OCPU / 8 GB RAM, x86_64 | 50 GB | 50 GB | One API, no worker; may be memory-constrained |
| Recommended stable internal preview | 4 OCPU / 16 GB RAM, x86_64 | 50 GB | 100 GB expandable | One API, no worker |
| Future production starting point | 4–8 OCPU / 32 GB RAM across redundant hosts | 50 GB each | Managed DB/object/vector storage after migration | Multiple API/worker processes only after storage redesign |

x86_64 is the safe initial architecture because that is the environment exercised
by the current lock and tests. Oracle Ampere/ARM64 may work with Python 3.12,
PyTorch, ONNX Runtime, Chroma, and Node images, but the complete pinned dependency
set and both Docker builds have **not** been built or tested on ARM64. Treat ARM as
a measured follow-up, not a cost-saving assumption.

The earlier repository audit estimated a 2–4 GB backend image and 1–2 GB steady
RAM, but artifact generation, model loading, ingestion, and concurrent requests
can exceed that. The 16 GB recommendation is headroom, not a measured peak.
Capture idle/peak RSS, CPU, startup time, upload latency, and disk I/O during the
authorized smoke/load test.

Storage growth cannot be predicted from the code alone. Measure:

`monthly growth = uploads + artifacts + DB delta + both vector-index deltas + retained traces`

Alert at 70% and 85% use and keep at least two full backup generations outside
the data volume; budget backup capacity at 2–4 times live storage until measured.
Only 80/443 should be public. Restrict SSH/22 to trusted operator IPs; keep
3000/8000 private. Outbound HTTPS/443 is required for providers and package/image
retrieval.

## Preparation

1. Create a non-root deployment operator with SSH-key access.
2. Patch the OS; enable time synchronization and unattended security updates.
3. Mount the block volume at `/srv/aira-x`; make storage writable by UID `10001`.
4. Install Docker from Docker's supported Ubuntu repository and verify Compose.
5. Permit inbound SSH only from the operator's trusted IP; permit public 80/443;
   do not expose ports 3000, 8000, or database storage.
6. Clone the repository into `/srv/aira-x/app` and check out an immutable,
   reviewed release SHA.
7. Copy `backend/.env.example` to `/srv/aira-x/secrets/backend.env`, replace every
   placeholder, set mode `0600`, and never copy it back into the repository.
8. Set production values:
   - `ENVIRONMENT=production`
   - `DATABASE_URL=sqlite:////app/storage/research_assistant.db`
   - all storage paths under `/app/storage`
   - exact `CORS_ORIGINS`; blank `CORS_ORIGIN_REGEX`
   - `DEMO_SEED_ENABLED=false`, `QUEUE_ARTIFACTS=false`
   - distinct `API_KEY` and `AUTH_SECRET`
   - selected Groq/search credentials
9. Make the Compose env-file path match the host secret file through a
   root-readable symlink or a deployment-only Compose override. Do not commit it.

## Build and preflight

Run only after deployment authorization:

1. `git status --short` must be empty and `git rev-parse HEAD` must equal the
   approved release SHA.
2. Build with `docker compose -f docker-compose.yml -f
   deploy/oracle/docker-compose.oracle.yml build`.
3. Scan the built image and dependency lock for known critical vulnerabilities.
4. Start backend only; inspect logs for configuration, database, and storage
   errors. Logs must not contain secrets.
5. Verify `GET http://127.0.0.1:8000/health` returns 200.
6. Verify `GET http://127.0.0.1:8000/ready` returns 200 with database, configured
   LLM, and storage checks passing. This does not verify provider connectivity.
7. Run the separately authorized provider/RAG/search smoke matrix.
8. Start frontend and verify it can reach the API through Nginx, not a public
   port.

## Nginx and streaming

Use `deploy/oracle/nginx/aira-x.conf.example` after replacing hostnames. The
streaming route requires `proxy_buffering off`, HTTP/1.1, long read/send timeouts,
and no response cache. Keep the upload limit aligned with
`MAX_UPLOAD_SIZE_MB`. Terminate TLS at Nginx and automate certificate renewal.

## Service operation

Manage Compose with a restricted systemd unit or an equivalent supervisor.
Docker restart policy covers process crashes; systemd ensures startup after host
boot. Uvicorn receives SIGTERM and drains requests during Compose's stop grace
period. The worker handles SIGTERM between jobs; it is disabled in the initial
SQLite topology.

Monitor:

- `/health` for liveness and `/ready` for routing readiness;
- container restart count and last exit code;
- HTTP 4xx/5xx, latency, and streaming disconnect rate;
- Groq/Tavily 401, 429, timeout, and quota responses;
- block-volume free space/inodes;
- SQLite integrity and backup/restore age;
- queue backlog only if a worker is later authorized;
- logs and traces for retention and accidental sensitive content.

The application has request logs and a rotating trace file, but no complete
central log retention policy. Configure Docker journaling or a host log agent
with bounded retention. Never log request authorization headers or secret values.

## Release and rollback

1. Back up storage and record the current release SHA.
2. Pull the reviewed release without rebasing or local edits.
3. Build a new immutable image tag containing the Git SHA.
4. Stop writes, start the new backend, and pass readiness plus smoke checks.
5. Start frontend only if its release is part of the authorization.
6. Observe the defined soak window before declaring success.

Rollback application code by selecting the prior immutable image/SHA and
restarting. Do **not** roll back the storage directory unless the new release
performed an incompatible data migration. This repository currently uses
`create_all` plus ad-hoc column healing rather than versioned migrations, so any
future schema-changing release requires its own forward/backward data plan.

Rollback triggers include readiness failure, persistent provider failures,
elevated 5xx/stream disconnects, corrupt writes, authentication bypass, secret
exposure, or a failed RAG citation check. Preserve logs and the failed image for
diagnosis; do not make an unrelated production hotfix.

## Go/no-go gate

Go only when all are true:

- reviewed release SHA and clean checkout;
- secrets present only in the host secret location;
- exact CORS origin approved;
- storage volume mounted, writable, and adequately sized;
- integrity-checked backup and successful isolated restore drill;
- image/dependency scan accepted;
- `/health` and `/ready` green;
- live Groq chat/streaming/RAG/search smoke tests green;
- rollback image and operator are available.

Any failed item is a no-go.
