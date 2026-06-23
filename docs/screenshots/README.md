# Screenshots

Portfolio captures for the root `README.md`. Every shot is taken against the
**deterministic demo seed**, so the visuals always match the documentation. The exact,
repeatable shot list lives in **[CAPTURE_PLAN.md](CAPTURE_PLAN.md)**; this file defines
the conventions every capture must follow.

> The `.png`/`.gif` binaries are intentionally **not committed** — only the folder
> structure (`.gitkeep`) and these conventions are. Captures populate the stable paths
> below.

## Folder structure

```
docs/screenshots/
├── chat/            # user product (streamed answer, artifact card)
├── operator/        # operator console (overview, readiness, drift recovery, sync detail)
├── observability/   # SLO / trend / alert panel
└── demo/            # demo seed tour + the demo GIF
```

## Asset map (stable paths)

| File | Capture | How to reach it |
|---|---|---|
| `chat/streamed-answer.png` | Chat: a streamed answer resolves | `/chat`, ask any question |
| `chat/artifact-card.png` | Chat: artifact card + download | `/chat`, request "build a deck" |
| `operator/console-overview.png` | The gated operator console | `/operator`, connect with the service key |
| `operator/readiness-states.png` | 6 targets across every readiness state | Incidents tab → External sync, after seeding |
| `observability/slo-panel.png` | SLO tiles, trends, drift backlog, alert | top of the Incidents tab, after seeding |
| `operator/drift-recovery.png` | A drifted incident's Refresh + Apply | expand the "ingest-worker" incident → History |
| `operator/incident-sync-detail.png` | Incident ↔ external linkage + records | expand a linked incident's sync detail |
| `demo/seed-tour.png` | The seeded guided tour | Demo data card, after seeding |
| `demo/demo-walkthrough.gif` *(optional)* | 30–45s demo clip | follow the demo script |

## Naming convention

- `category/subject[-state].png` — lowercase **kebab-case**, no spaces, no dates.
- Folder = category (`chat` / `operator` / `observability` / `demo`).
- One concept per file; prefer a descriptive `subject` (`readiness-states`, not `panel1`).

## Resolution & framing

- Viewport **1440×900**, browser zoom **100%**; capture at **2× / retina** when possible
  (minimum **1280px** wide).
- Crop out OS/browser chrome or use one consistent clean frame across all shots.
- No devtools, no unrelated tabs, no cursor mid-click unless it illustrates an action.

## Capture rules

- **Always capture on the demo seed** (`POST /operator/demo/seed`) — it is deterministic,
  so every capture is reproducible and matches the docs' stated numbers.
- The seed data is fully synthetic (`demo.aira-x.local`) — **nothing to redact**; never
  capture real targets, secrets, or personal accounts.
- Keep the same theme, zoom, and viewport across the whole set for a coherent gallery.
- Recapture all affected shots when the UI changes — stale screenshots are worse than none.

## Dark / light mode policy

- **Dark mode is canonical** — capture the full set in dark mode (it matches the operator
  console's primary look and the observability dashboard reads best there).
- A **single light-mode hero** of the operator console is optional, for contrast; if used,
  name it `operator/console-overview-light.png` and keep all *other* shots dark for
  consistency.
