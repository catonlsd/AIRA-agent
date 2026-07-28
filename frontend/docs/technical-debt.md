# AIRA-X Technical Debt Register

All entries use hardcoded typography, color, or sizing values that were intentionally deferred during the phase that discovered them. Each entry includes the target phase for resolution and the exact instance count at the time of deferral.

---

## TD-001

**Category:** `text-[10px]` badge/pill combos — sub-threshold accessibility candidates
**Instances:** 6
**Discovered:** Phase 2 — Typography migration (Step 3)
**Target phase:** Phase 4 — Component Polish
**Description:** Six `text-[10px]` instances remain in badge/pill interactive contexts: the nav item badge (`components/nav.tsx:167`), the StatusBadge pill in chat (`app/chat/page.tsx:513`), a resource type badge in settings (`app/settings/page.tsx:944`), a role suffix label in settings (`app/settings/page.tsx:675`), a task-status label in assistant-answer (`components/assistant-answer.tsx:276`), and a value type label in technical-details (`components/technical-details.tsx:48`). Accessibility fix (→ `type-caption`, 11px) was approved in principle during Phase 2 but deferred because all remaining instances are tight badge/pill components with combined `uppercase` + custom tracking patterns that require component-level refactoring to migrate cleanly.

---

## TD-002

**Category:** Raw Tailwind color tokens in `upload/page.tsx` and `citation-list.tsx`
**Instances:** 18
**Discovered:** Phase 2 — Typography migration (Step 3 audit)
**Target phase:** Phase 3 — Color Token Migration
**Description:** `app/upload/page.tsx` and `components/citation-list.tsx` use raw Tailwind color utilities (`text-slate-*`, `bg-blue-*`, `text-accent` without `var()`) throughout their typography-adjacent rules. These files are out of scope for the typography phase — modifying them requires the Phase 3 color audit to establish semantic color tokens first. Typography patterns in these files (e.g., `text-sm font-semibold`) were deliberately left unconverted to avoid partial migrations that would obscure color-phase work.

---

## TD-003

**Category:** Sub-threshold font sizes — `text-[11px]` and `text-[10px]` (covered above in TD-001)
**Instances:** 110
**Discovered:** Phase 2 — Typography migration (Step 0 audit + Step 3 residual scan)
**Target phase:** Phase 3 (batch decision) / Phase 4 (component-level)
**Description:** 110 instances of `text-[11px]` (≈ 0.6875rem) remain below the minimum approved token size that can be freely migrated without per-instance review. These span: nav item descriptions and the "Workspace" label (`components/nav.tsx`), all `font-mono text-[11px]` document IDs, timestamps, and tool internal names across agents/documents/history/overview/tools/workflows pages, operator section headers (post-redesign, now using `text-[11px]` not `text-xs`), approval and workflow `font-mono text-[11px]` breakall values, and the `SectionHeader` sub-label in `components/ui/primitives.tsx`. The `type-caption` class (11px) is the designated migration target, but each context must be individually confirmed for legibility and contrast before conversion. The operator redesign commits introduced `text-[11px] font-black uppercase` in place of `text-xs font-black uppercase` (the previous form was migrated to `type-label`; the redesigned form needs a new token or size adjustment decision).

---

## TD-004

**Category:** `font-bold` (weight 700) — no canonical weight token
**Instances:** 37
**Discovered:** Phase 2 — Typography migration (Step 3 residual scan)
**Target phase:** Phase 3 — Token Gap Resolution
**Description:** 37 instances use `font-bold` (weight 700) in contexts that are neither `font-black` (900, covered by existing weight tokens) nor `font-semibold` (600, covered by `--weight-body-strong`). Patterns include: `aira-chip` text (`text-xs font-bold` in ~10 hero chip divs across all routes), operator delivery/destination section labels (`text-xs font-bold uppercase tracking-[0.16em]`, 5 instances using custom tracking not in the token system), nav item link labels (`text-sm font-bold leading-none`, `components/nav.tsx:157`), nav brand subtitle (`text-xs font-semibold`, `components/nav.tsx:287`), chat info-tile headings and source tags (`text-sm font-bold`, `app/chat/page.tsx`), error/flash feedback text (`text-xs font-semibold text-[var(--danger/success)]`, multiple files), and primitive Tabs component (`text-xs font-bold`, `components/ui/primitives.tsx:93`). Resolution requires either defining `--weight-bold: 700` and a corresponding utility class, or a design decision to map these to the nearest existing token.

---

## TD-005

**Category:** Interactive button and CTA element typography
**Instances:** 87
**Discovered:** Phase 2 — Typography migration (Step 3 residual scan)
**Target phase:** Phase 3 — Component Token System
**Description:** 87 `<button>` and `<Link>` CTA elements carry `text-xs font-black` or `text-sm font-black` directly in their className strings. These are all interactive elements (confirmed by presence of `rounded-*`, `px-*`, `py-*`, `hover:*`, `transition` co-classes) and use semantic interactive-state colors (`--accent-foreground`, `--danger`, `--warning`, `--text-muted`). Button typography doesn't participate in document reading hierarchy — it's component-level styling. The typography phase governance scope covers document-hierarchy text. These instances require a dedicated button/interactive component token system, not the type-* utility classes.

---

## TD-006

**Category:** Form input field typography (`<input>` elements)
**Instances:** 5
**Discovered:** Phase 2 — Typography migration (Step 3 residual scan)
**Target phase:** Phase 3 — Component Token System
**Description:** Five `<input appearance-none>` elements carry `text-sm font-semibold text-[var(--text-strong)]` with `outline-none` and focus-state classes: two search/filter inputs in `app/approvals/page.tsx` (lines 1028, 1044), one in `app/tools/page.tsx` (line 777), and two in `app/workflows/page.tsx` (lines 1393, 1411). Form field text inherits from the system font stack and is styled by browser-native UA stylesheets in addition to our classes. These should be handled through a unified form input component rather than individual class migration.

---

## TD-007

**Category:** Alert/danger container divs with dynamic color state
**Instances:** 6
**Discovered:** Phase 2 — Typography migration (Step 3 residual scan)
**Target phase:** Phase 3 — Alert Component
**Description:** Six `<div>` container elements use `text-sm leading-6 text-[var(--danger)]` (or `text-xs leading-5 text-[var(--danger)]`) as a combined parent rule that cascades typography and danger color to all child content. Files: `app/approvals/page.tsx`, `app/settings/page.tsx`, `app/workflows/page.tsx`, and `app/workflows/[run_id]/page.tsx`. Replacing `text-sm leading-6` with `type-body` on a container div would change the inherited line-height for all children and risks layout shifts in multi-line alert bodies. Resolution requires extracting an `<Alert>` component with its own internal token composition.

---

## TD-008

**Category:** `<pre>` and code-block content areas
**Instances:** 10
**Discovered:** Phase 2 — Typography migration (Step 3 residual scan)
**Target phase:** Phase 4 — Component Polish
**Description:** Ten `<pre className="... text-xs leading-6">` elements in `app/workflows/[run_id]/page.tsx` (lines 694, 704, 747, 758, 768, 778, 860, 941, 1031) and `components/assistant-answer.tsx` (line 59) use `text-xs leading-6` (12px, 1.5rem absolute line-height). The `type-mono` class uses `var(--leading-body): 1.65` (relative), which would change line spacing inside these code blocks. Pre elements also have browser-default `font-family: monospace`, making the `type-mono` font-family declaration redundant. These need a dedicated `type-code-block` class (or equivalent) with absolute line-height to preserve fixed-width grid alignment before migration.

---

## TD-009

**Category:** `py-12` (48px) — upload drop-zone vertical padding
**Instances:** 1
**Discovered:** Phase 3 — Spacing (Step 0 audit)
**Target phase:** Phase 4 — Component Polish
**Description:** One instance of `py-12` (48px) in `app/upload/page.tsx`. This file is already out of scope for Phase 3 (TD-002 covers its raw Tailwind color tokens). The 48px value serves the drop-zone affordance specifically and has no parallel use elsewhere. It is not tokenized in the Phase 3 scale. Resolution: either add `--space-12: 3rem` to the scale in Phase 4 if other large drop-zone or modal contexts emerge, or keep as an explicit `py-12` utility in the upload component.

---

## TD-010

**Category:** `mt-20` (80px) — page-level vertical offset
**Instances:** 1
**Discovered:** Phase 3 — Spacing (Step 0 audit)
**Target phase:** Phase 4 — Component Polish
**Description:** One instance of `mt-20` (80px) used as a page-level top-margin offset (likely empty-state or above-fold breathing room). This value has no parallel use anywhere else in the codebase and is intentionally left as a Tailwind utility rather than introducing a token for a single-use case. Review in Phase 4: if additional 80px offsets appear, add `--space-20: 5rem` to the scale; if the single instance is an outlier, remove or replace with a layout-level token instead.

---

## TD-011

Category: Color tokens — pre element hardcoded hex foreground
Files: `app/globals.css` (pre rule, light/dark variants)
Instances: 2 (one per color-scheme)
Pattern: `pre { color: #e5edf8; }` (dark) / `[data-scheme="light"] pre { color: #c8f7dc; }` (light) — hardcoded hex colors
Gap: No `--code-text` or `--pre-foreground` token
Discovered: Phase 4 — Component Polish
Deferred to: Phase 6

---

## TD-012

Category: Color tokens — success border recipe
Files: `overview/page.tsx`, `workflows/page.tsx`, `documents/page.tsx`, `assistant-answer.tsx`
Instances: 4
Pattern: `color-mix(in srgb, var(--success) 34%, transparent)` — raw recipe, no token
Discovered: Phase 4 — Component Polish
Deferred to: Phase 6

---

## TD-013

**Category:** Duration tokens — legacy files still using `duration-300`
**Instances:** 3
**Discovered:** Phase 5 — Motion System
**Target phase:** Phase 6 — Color Token Migration
**Description:** `app/upload/page.tsx` and `components/citation-list.tsx` use Tailwind `duration-300` (300ms) on interactive elements instead of the Phase 5 `--duration-fast` / `--duration-base` tokens. These files are already out of scope for token migration due to their raw Tailwind color tokens (TD-002). Migrating duration in isolation would leave the files in an inconsistent partial-migration state. Resolution blocked by TD-002: once the blue-theme color tokens are replaced with semantic `var(--*)` tokens in Phase 6, duration can be migrated in the same pass.

---

## TD-014

**Category:** Duration tokens — `chat/chat.css` `.chat-button` raw duration
**Instances:** 1
**Discovered:** Phase 5 — Motion System
**Target phase:** Phase 6
**Description:** `app/chat/chat.css` line: `.chat-button { transition: all 0.2s ease; }` uses a hardcoded `0.2s` duration that is not wired to any `--duration-*` token. The `.chat-button` CSS class was out of scope for the Phase 5 TSX sweep (it is a CSS rule, not a TSX className string). Resolution: replace with `transition: all var(--duration-fast) var(--ease-out);` once a Phase 6 CSS sweep is approved, or deprecate `.chat-button` in favour of Tailwind utilities on the relevant elements in `chat/page.tsx`.

---

## TD-015

**Category:** React effect-driven state and data-loading patterns
**Instances:** 21 warnings after the Phase 1 release-stabilization fix
**Rule:** `react-hooks/set-state-in-effect`
**Severity:** Warning
**Discovered:** Release stabilization — Phase 1
**Target phase:** Phase 7 — frontend state/data-fetching cleanup, except the three
hydration/UI-state entries explicitly assigned to Phase 6B below

The original inventory contained 22 warnings: 21
`react-hooks/set-state-in-effect` warnings and one
`react-hooks/exhaustive-deps` warning. The missing dependency in
`app/settings/page.tsx` was release-relevant and fixed during stabilization. The
remaining warnings are exact below.

| File | Lines | Count | Release impact | Proposed resolution | Phase |
|---|---:|---:|---|---|---|
| `app/agents/page.tsx` | 360 | 1 | Low — initial list load; no loop observed | Move initial loading to a route/data boundary or a query hook | Phase 7 (neither 6A nor 6B) |
| `app/approvals/page.tsx` | 783, 848 | 2 | Medium — initial load and polling-state transition | Encapsulate polling in a reducer/query hook and derive idle state | Phase 7 (neither 6A nor 6B) |
| `app/chat/page.tsx` | 2701 | 1 | Low — one-time continuation hydration | Initialize continuation state before render or via an external-store hook | Phase 6B |
| `app/documents/page.tsx` | 335 | 1 | Low — initial list load; no repeated request observed | Move initial loading to a route/data boundary or query hook | Phase 7 (neither 6A nor 6B) |
| `app/history/page.tsx` | 338 | 1 | Low — initial list load; no repeated request observed | Move initial loading to a route/data boundary or query hook | Phase 7 (neither 6A nor 6B) |
| `app/operator/page.tsx` | 770, 778 | 2 | Medium — operator identity/auth verification and tab loading | Model verification/loading as an explicit reducer or query state machine | Phase 7 (neither 6A nor 6B) |
| `app/overview/page.tsx` | 314 | 1 | Low — initial metrics load | Move initial loading to a route/data boundary or query hook | Phase 7 (neither 6A nor 6B) |
| `app/settings/page.tsx` | 350, 586, 805, 1345 | 4 | Medium — health polling and four initial resource loads | Extract reusable polling/query hooks with cancellation and derived status | Phase 7 (neither 6A nor 6B) |
| `app/tools/page.tsx` | 558 | 1 | Low — initial list load | Move initial loading to a route/data boundary or query hook | Phase 7 (neither 6A nor 6B) |
| `app/workflows/[run_id]/page.tsx` | 1164, 1211 | 2 | Medium — run load and approval polling-state transition | Encapsulate run polling in a reducer/query hook and derive idle state | Phase 7 (neither 6A nor 6B) |
| `app/workflows/page.tsx` | 1106, 1148 | 2 | Medium — list load and approval polling-state transition | Encapsulate workflow polling in a reducer/query hook and derive idle state | Phase 7 (neither 6A nor 6B) |
| `components/nav.tsx` | 202 | 1 | Low — stored sidebar preference hydration | Use a lazy client-state source with a hydration-safe snapshot | Phase 6B |
| `components/theme-provider.tsx` | 62 | 1 | Low — stored theme override hydration | Use a hydration-safe external-store snapshot for the override | Phase 6B |
| `components/time-theme-control.tsx` | 14 | 1 | Low — mounted-state visual gate | Replace the mounted flag with a hydration-safe rendering strategy | Phase 6B |

These warnings are safe to defer because the complete TypeScript, logic-test,
production-build, and repeated browser-E2E walls pass; no request loop, stale
authentication decision, unbounded poller, or user-visible state failure was
observed. They remain visible warnings and must not be globally disabled.
