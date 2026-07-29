# AIRA-X persistence, backup, and recovery

## Initial-preview decision

Use **Option A: SQLite plus one persistent block-volume directory on one Oracle
VM**, with one API process and `QUEUE_ARTIFACTS=false`.

This is the smallest architecture the repository actually supports end to end.
Option B (managed PostgreSQL plus object storage) is the scale target, not a
Phase 3 deployment option: `requirements.txt` has no PostgreSQL driver, the
project has no schema-migration framework, file APIs assume local paths, and
vector persistence is local.

Do not run multiple API replicas against this SQLite design. Do not enable the
separate worker until queue concurrency and SQLite lock behavior have been
load-tested. A future PostgreSQL migration requires an explicit architecture
decision, driver, migrations, object-storage adapter, and rollback rehearsal.

## Data map

| Resource | Current implementation/location | Oracle mount and ownership | Backup / retention | Restart and replicas | Data-loss / restore behavior |
|---|---|---|---|---|---|
| Users/accounts, preferences, workspaces/memberships | SQLAlchemy rows in SQLite from `DATABASE_URL` | `/srv/aira-x/storage/research_assistant.db`, volume owned by UID `10001` | Daily coordinated backup, 7 daily + 4 weekly | Restart-safe; one writable replica only | Primary data; restore matching DB generation |
| Conversations and memory | SQLite rows | Same DB/mount/owner | Same DB schedule | Restart-safe; one writer | Lost after RPO if newest DB is unavailable |
| Document metadata and parsed chunk text | SQLite `documents`/`document_chunks` | Same DB/mount/owner | Same DB schedule | Restart-safe; one writer | Chunk text can rebuild vectors after a reindex tool exists |
| Uploaded source files | Local files in `UPLOAD_DIR` | `/srv/aira-x/storage/uploads`, UID `10001`, dirs `0750` | Daily coordinated backup, 7 + 4 | Restart-safe; not shared across hosts | Not rebuildable unless user re-uploads |
| Legacy embeddings/vector index | JSON at `VECTOR_DB_DIR/vectors.json` | `/srv/aira-x/storage/vector_index`, UID `10001` | Same coordinated generation as DB | Restart-safe; no multi-host writers | Portable JSON, but concurrent/interrupted writes risk divergence |
| Chroma embeddings/vector index | Persistent Chroma at `CHROMA_DIR` | `/srv/aira-x/storage/chroma`, UID `10001` | Same coordinated generation as DB | Restart-safe on same dependency version; no multi-host writers | Version-coupled; rebuild from DB chunks is safer than assuming portability |
| Generated artifacts | Local files in `ARTIFACTS_DIR` plus DB references/job results | `/srv/aira-x/storage/artifacts`, UID `10001`, dirs `0750` | Daily, 7 + 4 | Restart-safe; local to one host | Missing files leave broken references |
| Workflow/execution state and approvals | SQLite rows in flow/job/run tables | Same DB/mount/owner | Same DB schedule | Restart-safe; worker disabled initially | In-flight request may fail; durable state remains |
| Audit/activity/incident/webhook events | SQLite rows | Same DB/mount/owner | Same DB schedule | Restart-safe; one writer | Recover to DB backup point |
| Turn traces | Rotating JSONL from `AIRA_TRACE_LOG` | `/srv/aira-x/storage/traces.jsonl`, UID `10001` | Daily if policy requires; 7 days suggested | Restart-safe append; single host | Diagnostic only; may contain user-derived data |
| Operational logs | Container stdout/stderr and system journal | Host journal/log agent, root-controlled | Rotate by size/time; 14 days suggested for preview | Survives app restart, not host loss unless exported | Not product state; required for diagnosis |
| Configuration | Git SHA plus host-only env | App checkout plus `/srv/aira-x/secrets/backend.env` mode `0600` | Git for non-secret config; encrypted secret backup separately | Reload requires restart | Never restore a known-exposed secret; rotate it |

The upload path currently performs a coordinated dual-write to SQLite, the
legacy JSON index, and Chroma. Phase 3 makes Chroma ingestion mandatory and
attempts compensating deletion from both indexes when ingestion fails. This
reduces divergence but cannot provide an atomic transaction across three storage
engines. An interrupted process can still require reindexing. That limitation is
an explicit release risk.

## Host layout

Use a dedicated persistent block volume mounted at `/srv/aira-x`:

```text
/srv/aira-x/
  app/                  # checked-out release
  storage/
    research_assistant.db
    uploads/
    artifacts/
    vector_index/
    chroma/
    traces.jsonl
  secrets/backend.env   # root-readable only; never in Git
  backups/
```

The Oracle Compose override bind-mounts `/srv/aira-x/storage` to `/app/storage`.
Keep at least 20% disk free. Alert on disk usage, `/ready` failures, restart
loops, HTTP 5xx rate, and backup age.

## Backup procedure

For the internal preview, use a coordinated maintenance backup. This favors
recoverability over availability.

1. Announce a short write freeze.
2. Stop frontend and API containers gracefully. Confirm no worker is running.
3. Run SQLite integrity checking against the stopped database:
   `sqlite3 /srv/aira-x/storage/research_assistant.db "PRAGMA quick_check;"`.
4. Create a timestamped, encrypted archive or block-volume snapshot containing
   the entire `/srv/aira-x/storage` directory. Never include `secrets/backend.env`
   in an unencrypted data archive.
5. Record release SHA, archive checksum, database size, storage size, timestamp,
   and `quick_check` result in the backup log.
6. Restart the stack; verify `/health` and `/ready`.
7. Retain daily backups for 7 days and weekly backups for 4 weeks for the
   internal preview. Revisit after usage and policy requirements are known.

Target initial-preview objectives: **RPO 24 hours, RTO 4 hours**. These are
engineering targets, not verified guarantees, until a restore drill succeeds.

## Restore drill

Never test restore over the only production copy.

1. Provision an isolated directory/VM with the same release SHA and dependency
   image.
2. Verify the backup checksum, then restore the archive into an empty storage
   directory with ownership for container UID `10001`.
3. Run `PRAGMA integrity_check;` before startup.
4. Start one API process with external egress disabled or test credentials.
5. Verify `/health` and `/ready`.
6. Verify counts for users, documents, chunks, conversations, jobs, and
   artifacts against the backup manifest.
7. Download one restored upload and one artifact.
8. Run a document query and confirm citations reference the restored document.
9. If retrieval fails while DB chunks are intact, mark the drill failed and
   rebuild both indexes with a separately reviewed reindex tool. Such a tool is
   not currently present.
10. Record measured RTO and all gaps. A successful restore drill is required
    before calling backup/recovery production-ready.

Run an isolated restore drill before the internal preview and at least quarterly
thereafter, and after any storage/schema/index format change.

## Failure scenarios

- **SQLite corruption:** stop writes, preserve the damaged file, restore the
  newest integrity-checked backup, then replay only verified newer user data.
- **Index corruption:** preserve evidence, rebuild both indexes from relational
  chunks after a reviewed reindex command exists; never restore only one index.
- **Deleted upload/artifact:** restore the matching file and database generation
  together, or reconcile the dangling metadata explicitly.
- **Disk full:** stop ingestion/artifact creation, expand or free the dedicated
  volume, verify SQLite and both indexes, then resume.
- **Host loss:** attach/restore the volume on a replacement VM, deploy the exact
  release SHA, restore secrets separately, and perform the restore checks.
