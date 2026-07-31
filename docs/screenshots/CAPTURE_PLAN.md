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
```

The browser operator console is intentionally disabled in this phase. Operator-console
captures below are deferred until a server-side operator-auth boundary exists; never
place the service key in browser storage to reproduce them.

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
| 3 | Operator dashboard | `operator/console-overview.png` | deferred | seeded | Legacy Delivery console reference | Deferred pending server-side operator authentication |
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

## Shooting script (click-by-click, ~10 minutes)

Do these in order in one session so the demo seed is fresh and the theme is consistent.

**Set the stage (once):**
1. Both servers running; seed applied (Prerequisites above).
2. Open `http://localhost:3000`, toggle to **dark mode** (theme switch, top of the app).
3. Set the window so the app content is **1440px** wide; hide bookmarks/extra tabs.

**The 8 shots** (the bracketed values are the deterministic seed output — use them to
confirm you're on the right state before you click capture):

1. **`chat/streamed-answer.png`** — `/chat` → type *"What can you help me with?"* → Enter →
   wait for the streamed answer to finish → capture the **answer card** (crop to the
   conversation, not the whole window).
2. **`chat/artifact-card.png`** — `/chat` → type *"Build me a quarterly review deck"* →
   wait for the **artifact card** with a Download link → capture the card.
   *(If local execution isn't configured to emit an artifact, skip this one — see Missing
   gaps in the report.)*
3. **`operator/console-overview.png`** — deferred. Do not restore the legacy browser
   service-key flow; recapture only after server-side operator authentication exists.
4. **`operator/readiness-states.png`** — **Incidents** tab → the **External sync** panel →
   capture the panel showing [PagerDuty Prod = Ready, Opsgenie EU = Ready, PagerDuty
   Staging = Stale, Generic Webhook = Unverified, PagerDuty Legacy = Auth failed, Jira
   Bridge = Disabled], each with its recommended-action chip.
5. **`observability/slo-panel.png`** — **Incidents** tab → the **Sync observability** panel
   (top) → capture [SLO tiles ≈ readiness 40% / validation 33% / reconciliation 67% / sync
   67%, 24h trend pass-rates, **Drift backlog: 3**, a `repeated_auth_failures` candidate
   alert on PagerDuty Legacy].
6. **`operator/drift-recovery.png`** — **Incidents** tab → expand the **ingest-worker**
   incident → **History** → capture the **drifted** linkage line offering **Refresh** +
   **Apply** (the "no auto-heal" story).
7. **`operator/incident-sync-detail.png`** — **Incidents** tab → expand the **payments-api**
   incident → capture the sync detail: **Externally linked** (PD-4821) + Open link + the
   synced record + reconciliation summary.
8. **`demo/seed-tour.png`** — **Incidents** tab → the **Demo data** card → capture the
   5-step guided tour rendered inline.

## Pre-commit checklist (every shot)

- [ ] **Dark mode** on; same viewport/zoom across the whole set.
- [ ] **No secrets**: the service-key field is empty/dots; no real API key anywhere in frame.
- [ ] **No local-only URLs**: crop out the browser address bar (`localhost:3000`). On-page
      links to `demo.aira-x.local` are fine — that's the synthetic seed namespace.
- [ ] **Matches the seed values** in brackets above (deterministic; recapture if not).
- [ ] Saved at the exact path/filename from the shot list; ≥1280px wide.

## Final README wiring (one paste, after the 8 PNGs are in)

Replace the table under `## Screenshots` in the root `README.md` with this block so the
images render inline:

```markdown
| | |
|---|---|
| **Operator readiness** — every state + recommended action | **Sync observability** — SLOs, trends, drift, alert |
| ![Operator readiness](docs/screenshots/operator/readiness-states.png) | ![Sync observability](docs/screenshots/observability/slo-panel.png) |
| **Drift recovery** — explicit, audited (no auto-heal) | **Incident sync detail** — linkage + audit |
| ![Drift recovery](docs/screenshots/operator/drift-recovery.png) | ![Incident sync detail](docs/screenshots/operator/incident-sync-detail.png) |
| **Demo seed tour** — one click, deterministic | **Chat** — streamed answer |
| ![Demo tour](docs/screenshots/demo/seed-tour.png) | ![Chat](docs/screenshots/chat/streamed-answer.png) |

> Captured on the deterministic demo seed (`POST /operator/demo/seed`). Full set +
> conventions: [docs/screenshots/](docs/screenshots/).
```

Then `git add docs/screenshots/**/*.png README.md` and commit. (Binaries: keep them
committed for the portfolio — they're small synthetic-data PNGs.)

## Demo GIF (optional, highest-impact)

Record a 30–45s clip of shots 4 → 5 → 6 (readiness → observability → expand ingest-worker
→ Refresh/Apply). Use any screen recorder; export ≤ 5 MB; save as
`demo/demo-walkthrough.gif`. Embed at the very top of the README, above the badges.

## After capture — verify

```bash
python -m pytest backend/tests/test_docs_packaging.py backend/tests/test_repo_professionalization.py -q -p no:randomly
# Confirm every referenced PNG now exists and the README renders on GitHub.
```
