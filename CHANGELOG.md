# Changelog

All notable changes to AIRA-X are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Repository professionalization (Phase 8):** OSS governance (`CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`), GitHub issue/PR templates, and three
  focused, parallel CI workflows — `fast-check` (backend + frontend), `e2e` (Playwright),
  and `docs` (packaging/professionalization gates).
- Release management: `docs/RELEASE_PROCESS.md` (versioning, release & rollback
  checklists, changelog process) and this `CHANGELOG.md`.
- `docs/DEPLOYMENT_BLUEPRINT.md` (single-VM, docker-compose, future Kubernetes path).
- Portfolio assets: `docs/PORTFOLIO_GUIDE.md` (role-based reading orders, demo script,
  talking points) and `docs/RESUME_BULLETS.md`.
- Quality-gate test `tests/test_repo_professionalization.py` pinning the OSS/CI/release
  files so they cannot silently disappear.

### Changed
- Replaced the monolithic `ci.yml` with the three focused, parallelized workflows above.

> Phase 8 is process/tooling only — **no product, API, DB, UI, or incident-sync behavior
> changed.**

---

## [0.1.0] — 2026-06-23

First public milestone — the platform built across Phases 1–7. Two production-grade
surfaces (a conversational AI assistant + an operator-grade incident-sync & observability
platform) behind one codebase.

### Added

- **Conversational assistant** — one `AssistantSupervisor` routing chat, web research,
  document Q&A (ChromaDB + local embeddings, grounded citations), and approval-gated safe
  execution, behind a streaming SSE API and a Next.js UI. Accounts, workspaces, roles,
  scoped preferences, run history, and per-turn tracing.
- **Incident sync (operator product)** — outbound-primary export of incident transitions
  to external tools via 4 capability-honest adapters (generic, PagerDuty, Opsgenie rich,
  Jira outbound-only) and 5 onboarding profiles. Local state stays the source of truth.
- **Capability / policy / profile model** — three separated layers with per-decision
  `source` attribution; overrides can only narrow within adapter capability.
- **Readiness model** — 8 computed states (never stored stale) from durable evidence via
  preflight `validate` + safe synthetic `test`; secret rotation invalidates trust.
- **Drift & deliberate recovery** — bounded inbound `refresh` (observe-only, never
  mutates local state); explicit, audited `apply` / `relink` / `detach` / `redrive`.
- **Observability** — deterministic, computed-on-read metrics: readiness distribution,
  24h/7d/30d SLO trends, drift snapshot, and candidate alerts (observations, never
  paging). No duplicate storage, no background aggregation.
- **Operational guidance** — per-state `recommended_action`, 12 runbooks, and a
  troubleshooting matrix; all deterministic, never AI advice.
- **Demo mode** — one-click, deterministic, namespaced showcase data + guided tour;
  non-destructive (real data provably survives a reset).
- **Production posture** — `/health` + `/ready`, API-key operator gating, rate limiting,
  security headers, CORS, self-healing schema (SQLite → Postgres via one env var).
- **Portfolio docs (Phase 7)** — overhauled README, `ARCHITECTURE.md` (Mermaid flows),
  `ENGINEERING_DECISIONS.md`, `DEMO_WALKTHROUGH.md`, `PLATFORM_SUMMARY.md`.

### Testing

- 939 backend tests (deterministic), 104 frontend pure-logic tests, 6 hermetic Playwright
  E2E tests, plus type-check / lint / build gates.

[Unreleased]: https://github.com/catonlsd/AIRA-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/catonlsd/AIRA-agent/releases/tag/v0.1.0
