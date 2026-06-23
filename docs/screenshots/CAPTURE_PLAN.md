# Screenshot capture plan

The exact, repeatable shot list that turns AIRA-X's README from "reads impressive" into
"looks real." Every shot is taken against the **deterministic demo seed**, so what you
capture matches what the docs describe — same targets, same SLOs, same drift backlog,
same alert, every time.

> **Do not invent screenshots.** Capture only the real, running UI on the seed data.
> Asset paths below are stable; future captures populate them.

---

## Prerequisites (one-time)

```bash
# 1. Backend (operator key REQUIRED so /operator is reachable)
cd backend && cp .env.example .env      # set GROQ_API_KEY and API_KEY=demo-operator-key
python -m uvicorn app.main:app --reload --port 8000

# 2. Frontend
cd frontend && npm install && npm run dev      # http://localhost:3000

# 3. Seed the deterministic showcase (operator key)
curl -s -X POST localhost:8000/operator/demo/seed -H "X-API-Key: demo-operator-key"
#   …or click "Seed demo data" in the operator console → Incidents tab.
```

**Capture environment (keep constant across all shots):**
- Viewport **1440×900**, browser zoom **100%**, capture at **2× / retina** if possible.
- **Dark mode** is canonical (see `README.md` → Capture rules). One light-mode hero is optional.
- Crop out OS/browser chrome (or use a clean, consistent frame). No devtools, no personal tabs.
- The seed data is fully synthetic (`demo.aira-x.local`) — nothing to redact.

---

## The shot list (8 assets · 7 categories)

| # | Category | Filename | Route | Required seeded state | UI section | Why it matters |
|---|---|---|---|---|---|---|
| 1 | Chat experience | `chat/streamed-answer.png` | `/chat` | none — just ask a question | The answer card after a streamed response resolves | Proves the core product works end-to-end (real SSE), not a mockup |
| 2 | Chat experience | `chat/artifact-card.png` | `/chat` | none — send a "build a deck" request | The artifact card with title + working **Download** link | Shows artifact generation/delivery — a tangible output, not just text |
| 3 | Operator dashboard | `operator/console-overview.png` | `/operator` (connected with the service key) | seeded | The Delivery console header + top-level panels | Establishes the gated operator surface — "this is operated, not just used" |
| 4 | Readiness states | `operator/readiness-states.png` | `/operator` → **Incidents** tab | seeded | The **External sync** panel: 6 targets across ready / stale / unverified / auth-failed / disabled, each with a recommended action | The computed readiness model — the single strongest "production systems" signal |
| 5 | Observability / SLO | `observability/slo-panel.png` | `/operator` → **Incidents** tab | seeded | The **Sync observability** panel: SLO tiles (~40% readiness, 33/67/67%), 24h trend pass-rates, drift backlog 3, the `repeated_auth_failures` candidate alert | Deterministic, computed-on-read observability — reads like an SRE dashboard |
| 6 | Drift detection & recovery | `operator/drift-recovery.png` | `/operator` → **Incidents** tab | seeded | Expand the **ingest-worker** incident → **History**: "drifted" linkage with **Refresh** + **Apply** | Deliberate, audited recovery (no auto-heal) — the core trust story, made visible |
| 7 | Demo seed walkthrough | `demo/seed-tour.png` | `/operator` → **Incidents** tab | seeded | The **Demo data** card with the 5-step guided tour rendered inline | Instant demonstrability — "one click, fully populated, namespaced, safe" |
| 8 | Incident sync detail | `operator/incident-sync-detail.png` | `/operator` → **Incidents** tab | seeded | Expand a **linked** incident (e.g. payments-api): external ref + Open link, sync records, reconciliation summary | The incident ↔ external linkage + durable audit trail behind every state |

**Category coverage:** 1 Chat (#1,2) · 2 Operator dashboard (#3) · 3 Readiness states (#4) ·
4 Observability/SLO (#5) · 5 Drift & recovery (#6) · 6 Demo walkthrough (#7) ·
7 Incident sync detail (#8).

---

## Optional: a 30–45s demo GIF/MP4

One short clip of the demo script (`docs/DEMO_WALKTHROUGH.md` §1–§6): seed → readiness →
observability → expand a drifted incident → Refresh/Apply. Save as
`demo/demo-walkthrough.gif` (or `.mp4`) and embed at the top of the README. This is the
single highest-impact asset for a recruiter's first 3 seconds — capture it last, once the
stills look right.

---

## After capture

1. Drop each `.png` at its path above (they are git-ignored as binaries unless you choose
   to commit them — see `README.md` in this folder).
2. The root `README.md` → **Screenshots** table already references these stable paths;
   once the files exist they render inline (swap the table rows for `![alt](path)` embeds
   if you want full-width images).
3. Re-run `python -m pytest backend/tests/test_docs_packaging.py -q` to confirm docs
   integrity.
