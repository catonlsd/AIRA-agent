# AIRA-X — Deterministic E2E suite (Playwright)

A small, **hermetic** browser suite that proves the most important product and operator
flows hold together in the real Next.js app. Every test stubs the backend at the
network layer (`page.route`), so there is **no real API, no LLM, no database, and no
third-party calls** — fast, deterministic, and CI-friendly. This is the layer the
backend wall (`backend/tests`, 900+ tests) and the pure frontend unit tests
(`lib/operator.test.mts`) cannot cover: the actual browser wiring.

## What it covers (6 tests, ~11s)

| Spec | Flow | Proves |
|---|---|---|
| `product-chat.spec.ts` | Ask a question → streamed answer resolves | Core product path (real SSE render) |
| `chat-artifact.spec.ts` | Build request → artifact card + download link | Artifact generation/delivery render |
| `execution-approval.spec.ts` | Plan-ready → **Approve** → resolves | Execution/approval round-trip |
| `operator-readiness.spec.ts` | Connect → **Validate** → Ready → **Test** | Operator target readiness (top commercial signal) |
| `operator-readiness.spec.ts` | Wrong key rejected | Operator-only separation guardrail |
| `operator-incident-sync.spec.ts` | Inspect linked incident → **Refresh** | Incident → external-sync → recheck |

## Design rules
- **Deterministic only.** No timing luck, no real network, no flaky waits — explicit
  `expect(...).toBeVisible()` conditions, never `sleep`.
- **Stable selectors.** Roles, exact text, and existing product classes
  (`.artifact-card`, `.aira-answer-card`). **Zero test-only DOM hooks** were added to
  the product — nothing leaks into the real UX.
- **Seeded fixtures** live in `helpers.ts` (`mockOperator`, `mockStream`, `seedTarget`,
  `seedIncident`, `artifactFinal`, `planFinal`). One broad fallback (`seedFallback`)
  returns empty `200`s for any un-stubbed call so a test never fails on noise.
- **Operator separation respected.** The operator flows go through the real
  service-key connect screen; a rejected key never reaches the console.

## Run it

```bash
cd frontend
npm run e2e:install   # one-time: download the chromium browser
npm run e2e           # runs the suite (boots `next dev -p 3100` automatically)
npm run e2e:ui        # interactive debugging
```

The Playwright `webServer` starts the dev server itself; locally it reuses an existing
one if you already have `next dev` running on port 3100.

## CI strategy (stratified)

Keep the **fast wall** and the **critical E2E lane** separate so day-to-day velocity
isn't gated on browsers:

1. **Fast wall** (every push): `backend` `pytest`, then `frontend` `tsc --noEmit` +
   `node --test lib/*.test.mts` + `eslint` + `next build`.
2. **Critical E2E lane** (PRs / pre-release): `npm run e2e:install && npm run e2e`
   (Chromium only). `CI=1` enables 1 retry + 2 workers + the HTML report.

The suite is intentionally **small** — add a test only for a flow a recruiter,
operator, or demo viewer would actually touch. Resist growing it into a giant,
DOM-coupled browser suite.
