# AIRA-X Design System

## Phase Status

| Phase | Scope | Status |
|---|---|---|
| Phase 1 | Surface contract (8 tokens) + radius scale | **Frozen** |
| Phase 2 | Typography contract (12 size + 7 weight + 5 leading + 5 tracking tokens) + 13 utility classes | **Frozen** |
| Phase 3 | Spacing contract (10 tokens, 8px-base scale with approved half-steps) | **Frozen** |
| Phase 4 | Component polish; badge/pill refactor; `<pre>` block tokens; form input tokens | **Frozen** |
| Phase 5 | Motion system — duration tokens, transition migration, lift constraint, press states, reduced-motion spinner | **Frozen** |

---

## Phase 1 — Surface Contract

### 8-Token Surface API

All component backgrounds must reference these tokens. Direct use of `--bg`, `--surface`, `--surface-soft`, `--surface-muted`, `--surface-strong` in new code is deprecated after Phase 1.

| Token | Night/SSR default | Role |
|---|---|---|
| `--canvas` | `#2e2c7a` | Deepest background — body and overscroll edges |
| `--workspace` | `rgba(60, 58, 130, 0.75)` | Main layout content area (`main.layout-workspace`) |
| `--surface-primary` | `rgba(50, 48, 110, 0.9)` | Cards, panels |
| `--surface-secondary` | `rgba(60, 58, 130, 0.75)` | Inputs, nested surfaces |
| `--surface-hover` | `rgba(255, 255, 255, 0.06)` | Hover state overlay |
| `--surface-active` | `#323070` | Pressed / selected state |
| `--surface-border` | `rgba(255, 255, 255, 0.1)` | Border on surface elements |
| `--surface-highlight` | `rgba(255, 255, 255, 0.03)` | Subtle inner rim highlight (dark themes) |

Each theme block (`[data-theme="*"]`) overrides all 8 tokens. Back-compat aliases
(`--surface`, `--surface-soft`, `--surface-muted`, `--surface-strong`) still point
to the nearest new tokens because active consumers remain. Their migration and
removal are tracked by TD-016 for Phase 6A.

### Radius Scale

Named in `px` for precision. Frozen after Phase 1.

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | `6px` | Badges, tags, small chips |
| `--radius-md` | `10px` | Inputs, buttons, small cards |
| `--radius-lg` | `14px` | Standard cards, panels |
| `--radius-xl` | `20px` | Hero cards, modals, large surfaces |
| `--radius-full` | `9999px` | Pills, avatars |

Back-compat aliases (do not use in new code):
- `--radius-xs` → `var(--radius-sm)` (was `0.375rem`)
- `--radius` → `var(--radius-md)` (was `0.75rem`)
- `--radius-pill` → `var(--radius-full)` (was `999px`)

Legacy radius aliases still have active consumers. Their migration and removal are
tracked together with the surface aliases in TD-016 for Phase 6A.

---

## Phase 2 — Typography Contract

### Governance Rules

1. **Single responsibility** — only `font-size`, `font-weight`, `line-height`, `letter-spacing` are in scope for type tokens. Text color is always separate (`--text-strong` / `--text` / `--text-muted` / `--text-subtle`).
2. **No new tokens without approval** — adding a token requires explicit sign-off and must document the derivation source.
3. **Freeze gate** — the contract below is immutable after Phase 2. Phase 3 changes go through a new approval gate.
4. **Utility classes only** — consumer code uses `.type-*` classes, never raw `font-size` / `font-weight` / `line-height` / `letter-spacing` Tailwind utilities in document-hierarchy contexts.

### Size Tokens

All derived from the Step 0 audit of the production codebase. Zero visual change from pre-migration rendering.

| Token | Value | Tailwind equiv | Role |
|---|---|---|---|
| `--type-display` | `2.25rem` | `text-4xl` (36px) | Page hero heading — every route |
| `--type-metric` | `1.875rem` | `text-3xl` (30px) | Large KPI number in dashboard |
| `--type-metric-sm` | `1.5rem` | `text-2xl` (24px) | Secondary stat display |
| `--type-heading-xl` | `1.25rem` | `text-xl` (20px) | Nav brand, medium sub-page h2 |
| `--type-heading` | `1.125rem` | `text-lg` (18px) | Card / panel title |
| `--type-heading-sm` | `1rem` | `text-base` (16px) | Item / step heading in a list |
| `--type-heading-xs` | `0.875rem` | `text-sm` (14px) | Compact heading in dense lists |
| `--type-body` | `0.875rem` | `text-sm` (14px) | Primary body prose |
| `--type-body-sm` | `0.75rem` | `text-xs` (12px) | Secondary body, card footer |
| `--type-label` | `0.75rem` | `text-xs` (12px) | ALL-CAPS section labels |
| `--type-caption` | `0.6875rem` | `text-[11px]` (11px) | Metadata, timestamps, badges |
| `--type-mono` | `0.6875rem` | `text-[11px]` (11px) | IDs, filenames, inline code |

**Floor:** `0.6875rem` (11px). Sizes below this floor require explicit accessibility review before being added.

### Weight Tokens

| Token | Value | CSS keyword | Role |
|---|---|---|---|
| `--weight-display` | `900` | `font-black` | Page headings (confirmed all 9 routes) |
| `--weight-heading` | `900` | `font-black` | Card / panel / item headings |
| `--weight-label` | `900` | `font-black` | ALL-CAPS section labels (~50 instances) |
| `--weight-body` | `400` | `normal` | Body prose |
| `--weight-body-strong` | `600` | `font-semibold` | Body inline emphasis, form values |
| `--weight-metric` | `900` | `font-black` | All KPI / stat numbers |
| `--weight-mono` | `400` | `normal` | IDs, code |

**Gap (TD-004):** `font-bold` (700) has no canonical token. Affects `aira-chip` text, nav link labels, operator section headers (post-redesign), error/flash feedback text. Target: Phase 6A.

### Line-Height Tokens

| Token | Value | Role |
|---|---|---|
| `--leading-display` | `1.2` | h1..h6 element rule |
| `--leading-heading` | `1.2` | All heading elements |
| `--leading-body` | `1.65` | p element rule |
| `--leading-caption` | `1.4` | Metadata, badge labels, timestamps |
| `--leading-metric` | `1.1` | Tight for numeric displays |

### Letter-Spacing Tokens

| Token | Value | Usage note |
|---|---|---|
| `--tracking-display` | `-0.025em` | `.tracking-tight` class on display headings (specificity 0-1-0) |
| `--tracking-heading` | `-0.035em` | h1..h6 element rule (specificity 0-0-1, no class override) |
| `--tracking-label` | `0.16em` | ALL-CAPS section labels |
| `--tracking-body` | `0em` | Body text — no tracking |
| `--tracking-mono` | `0em` | Monospace — never tracks |

**Split rationale:** `--tracking-display` and `--tracking-heading` are distinct because the element rule (lower specificity) is overridden by `tracking-tight` on display headings. This is intentional: display headings need tighter tracking than the element default to maintain the visual hierarchy.

### Utility Classes

Use exactly one `.type-*` class per text element. Never compose two. Text color is always added separately.

```css
.type-display {
  font-size: var(--type-display);          /* 2.25rem / 36px */
  font-weight: var(--weight-display);      /* 900 */
  line-height: var(--leading-display);     /* 1.2 */
  letter-spacing: var(--tracking-display); /* -0.025em */
}

.type-metric {
  font-size: var(--type-metric);           /* 1.875rem / 30px */
  font-weight: var(--weight-metric);       /* 900 */
  line-height: var(--leading-metric);      /* 1.1 */
  letter-spacing: var(--tracking-display); /* -0.025em */
  font-variant-numeric: tabular-nums;
}

.type-metric-sm {
  font-size: var(--type-metric-sm);        /* 1.5rem / 24px */
  font-weight: var(--weight-metric);       /* 900 */
  line-height: var(--leading-metric);      /* 1.1 */
  letter-spacing: var(--tracking-display); /* -0.025em */
  font-variant-numeric: tabular-nums;
}

.type-heading-xl {
  font-size: var(--type-heading-xl);       /* 1.25rem / 20px */
  font-weight: var(--weight-heading);      /* 900 */
  line-height: var(--leading-heading);     /* 1.2 */
  letter-spacing: var(--tracking-heading); /* -0.035em */
}

.type-heading {
  font-size: var(--type-heading);          /* 1.125rem / 18px */
  font-weight: var(--weight-heading);      /* 900 */
  line-height: var(--leading-heading);     /* 1.2 */
  letter-spacing: var(--tracking-heading); /* -0.035em */
}

.type-heading-sm {
  font-size: var(--type-heading-sm);       /* 1rem / 16px */
  font-weight: var(--weight-heading);      /* 900 */
  line-height: var(--leading-heading);     /* 1.2 */
  letter-spacing: var(--tracking-heading); /* -0.035em */
}

.type-heading-xs {
  font-size: var(--type-heading-xs);       /* 0.875rem / 14px */
  font-weight: var(--weight-heading);      /* 900 */
  line-height: var(--leading-heading);     /* 1.2 */
  letter-spacing: var(--tracking-heading); /* -0.035em */
}

.type-label {
  font-size: var(--type-label);            /* 0.75rem / 12px */
  font-weight: var(--weight-label);        /* 900 */
  line-height: var(--leading-caption);     /* 1.4 */
  letter-spacing: var(--tracking-label);   /* 0.16em */
  text-transform: uppercase;
}

.type-body {
  font-size: var(--type-body);             /* 0.875rem / 14px */
  font-weight: var(--weight-body);         /* 400 */
  line-height: var(--leading-body);        /* 1.65 */
  letter-spacing: var(--tracking-body);    /* 0em */
}

.type-body-strong {
  font-size: var(--type-body);             /* 0.875rem / 14px */
  font-weight: var(--weight-body-strong);  /* 600 */
  line-height: var(--leading-body);        /* 1.65 */
  letter-spacing: var(--tracking-body);    /* 0em */
}

.type-body-sm {
  font-size: var(--type-body-sm);          /* 0.75rem / 12px */
  font-weight: var(--weight-body);         /* 400 */
  line-height: var(--leading-body);        /* 1.65 */
  letter-spacing: var(--tracking-body);    /* 0em */
}

.type-caption {
  font-size: var(--type-caption);          /* 0.6875rem / 11px */
  font-weight: var(--weight-body);         /* 400 */
  line-height: var(--leading-caption);     /* 1.4 */
  letter-spacing: var(--tracking-body);    /* 0em */
}

.type-mono {
  font-size: var(--type-mono);             /* 0.6875rem / 11px */
  font-weight: var(--weight-mono);         /* 400 */
  line-height: var(--leading-body);        /* 1.65 */
  letter-spacing: var(--tracking-mono);    /* 0em */
  font-family: var(--font-mono), ui-monospace, "SFMono-Regular", Consolas, monospace;
}
```

### Usage Quick Reference

| Context | Class | Color token |
|---|---|---|
| Route hero `<h1>` | `type-display` | `text-[var(--text-strong)]` or `aira-gradient-text` |
| Dashboard KPI value | `type-metric` | `text-[var(--text-strong)]` |
| Secondary stat | `type-metric-sm` | `text-[var(--text-strong)]` |
| Nav brand / sub-page h2 | `type-heading-xl` | `text-[var(--text-strong)]` |
| Card / panel title `<h2>` | `type-heading` | `text-[var(--text-strong)]` |
| List item / step heading `<h3>` | `type-heading-sm` | `text-[var(--text-strong)]` |
| Dense list heading | `type-heading-xs` | `text-[var(--text-strong)]` |
| Body paragraph | `type-body` | `text-[var(--text-muted)]` |
| Emphasized body / form value | `type-body-strong` | `text-[var(--text-strong)]` |
| Secondary / footer copy | `type-body-sm` | `text-[var(--text-muted)]` |
| ALL-CAPS section label | `type-label` | `text-[var(--text-subtle)]` |
| Timestamp / badge metadata | `type-caption` | `text-[var(--text-subtle)]` |
| ID / filename / inline code | `type-mono` | `text-[var(--text-subtle)]` |

### Documented Exceptions (approved, not TD)

- **`chat/page.tsx` hero** — `type-display md:text-[2.6rem] md:leading-[1.1]`: responsive override at `md:` breakpoint preserves breakpoint-specific sizing above the base token. Intentional; no equivalent responsive token exists.
- **`workflows/[run_id]/page.tsx` run goal** — `type-heading leading-7`: explicit `leading-7` override on long user-supplied text for readability. Token sets 1.2; override is 1.75rem absolute.
- **Conditional mono override** — `cn("type-body-strong ...", mono && "font-mono text-xs")`: component-level weight override cascade. Intentional; mono prop overrides size+family only, not role.
- **`--tracking-display` vs `--tracking-heading` split**: see letter-spacing rationale above.

---

## Phase 3 — Spacing Contract

### Governance Rules

1. **Single responsibility** — only `padding`, `margin`, `gap`, and `space-between` values are in scope. Width, height, and layout sizing are separate.
2. **No new tokens without approval** — the 10-token scale below is frozen. Half-steps beyond `--space-1-5` and `--space-2-5` require explicit sign-off.
3. **Peripheral exclusions** — `48px` (`py-12`) and `80px` (`mt-20`) are intentionally not tokenized. They remain as Tailwind utilities. See TD-009 and TD-010 in `frontend/docs/technical-debt.md`.
4. **Fractional harmonization** — globals.css component values that fall between token steps (e.g., 6.4px, 7.2px) are mapped to the nearest token by visual judgment, not arithmetic rounding alone.

### Token Scale

All values are 8px-base with two approved half-steps (6px, 10px) for badge/pill micro-spacing.

| Token | Value | px | Tailwind equiv | Primary role |
|---|---|---|---|---|
| `--space-1` | `0.25rem` | 4px | `1` | Icon gutters, minimal chip vertical |
| `--space-1-5` | `0.375rem` | 6px | `1.5` | Pill/badge vertical padding, icon-label gaps |
| `--space-2` | `0.5rem` | 8px | `2` | Dense layout gap, tight follow-on margin |
| `--space-2-5` | `0.625rem` | 10px | `2.5` | Badge/pill horizontal padding |
| `--space-3` | `0.75rem` | 12px | `3` | Standard inter-element gap, compact padding |
| `--space-4` | `1rem` | 16px | `4` | Standard card padding, section stack margin |
| `--space-5` | `1.25rem` | 20px | `5` | Panel padding, section break margin |
| `--space-6` | `1.5rem` | 24px | `6` | Generous section padding, grid column gap |
| `--space-8` | `2rem` | 32px | `8` | Large section, hero inner padding |
| `--space-10` | `2.5rem` | 40px | `10` | Hero emphasis, search-icon inset |

### Fractional Value Harmonization Map

globals.css component rules that used raw rem values — resolved to nearest token by visual judgment:

| Original value | px equiv | Maps to | Token |
|---|---|---|---|
| `0.25rem` | 4px | exact | `--space-1` |
| `0.3rem` | 4.8px | → 4px (chip vertical, tight) | `--space-1` |
| `0.375rem` | 6px | exact | `--space-1-5` |
| `0.4rem` | 6.4px | → 6px (status indicator gap) | `--space-1-5` |
| `0.45rem` | 7.2px | → 6px (chip gap — visual match) | `--space-1-5` |
| `0.5rem` | 8px | exact | `--space-2` |
| `0.6rem` | 9.6px | → 10px (status badge horizontal) | `--space-2-5` |
| `0.625rem` | 10px | exact | `--space-2-5` |
| `0.75rem` | 12px | exact | `--space-3` |
| `0.85rem` | 13.6px | → 12px (link pill horizontal — tight) | `--space-3` |
| `0.9rem` | 14.4px | → 12px (quick action horizontal — tight) | `--space-3` |
| `1rem` | 16px | exact | `--space-4` |
| `2rem` | 32px | exact | `--space-8` |

### Not Tokenized (TD)

- `48px` (`py-12`) — upload drop zone only. TD-009, target Phase 6A.
- `80px` (`mt-20`) — single page-level offset. TD-010, target Phase 6A.

### Delivery Record

**Step 1** — `--space-*` token block added to `:root` in `frontend/app/globals.css`. 10 tokens, zero visual change at delivery.

**Step 2** — `frontend/tailwind.config.ts` extended with `spacing` block. All 10 scale keys override Tailwind defaults with `var(--space-*)` references. Every `gap-*`, `p-*`, `px-*`, `py-*`, `mt-*`, `mb-*`, `space-y-*` utility in `.tsx` files now resolves through the token layer automatically, with no `.tsx` files edited.

**Step 3** — `frontend/app/globals.css` component-scoped rules migrated. 12 substitutions across 8 selectors (`.aira-chip`, `.pro-kicker`, `.status-success/warning/danger/info`, `.system-status-live`, `.pro-quick-action`, `.pro-link-row`, `.pro-link-pill`, `.assistant-empty-shell`, `.aira-focus-hint`). All fractional rem values replaced with nearest `var(--space-*)` per approved harmonization map. Visual delta: ≤2px on harmonized values; 6 exact matches with zero pixel change.

**Visual QA** — confirmed across nav, operator, approvals, assistant-answer chips, and status badges. `system-status-live::before` dot confirmed as Lucide SVG (not CSS pseudo-element); no pseudo-element spacing to check.

---

## Phase 4 — Component Polish

### Governance Rules

1. **Single responsibility** — only component-semantic token gaps are in scope. Generic structural `rounded-2xl` (cards, icon containers) are explicitly excluded.
2. **No new tokens without approval** — all 8 tokens added in Phase 4 were individually approved before any component code was written.
3. **Human visual approval required** — no self-certification. Build gates verify correctness; visual QA is done by the team.
4. **Priority 1 scope** — Badges/pills, form inputs, alert containers, code/pre blocks, and CTA buttons. Dense-list metadata (operator page) and upload page are deferred.

### New `:root` Tokens (Phase 4)

| Token | Value | Role |
|---|---|---|
| `--radius-2xl` | `24px` | Large inputs, alert containers, code blocks, CTA buttons |
| `--leading-code` | `1.5rem` | ABSOLUTE — pre/code blocks; 24px fixed grid at any font size |
| `--leading-alert` | `1.25rem` | ABSOLUTE — alert prose; 20px fixed rhythm |
| `--danger-border` | `color-mix(in srgb, var(--danger) 34%, transparent)` | Danger container borders |
| `--warning-border` | `color-mix(in srgb, var(--warning) 34%, transparent)` | Warning container borders |
| `--accent-border` | `color-mix(in srgb, var(--accent) 22%, transparent)` | Code block accent borders |
| `--on-danger` | `#ffffff` | Text on solid danger backgrounds (reserved; 0 callsites in Phase 4) |
| `--on-warning` | `#ffffff` | Text on solid warning backgrounds |

**Note on absolute leading:** `--leading-code` and `--leading-alert` are intentionally `rem` (not unitless ratios) to preserve the fixed-height rendering of pre/alert elements at all font sizes. This is an exception to the relative leading convention used by all Phase 2 tokens.

### Tailwind Config Additions (Phase 4)

```typescript
// frontend/tailwind.config.ts — inside extend:
fontWeight: {
  'black': 'var(--weight-heading)',   // font-black → var(--weight-heading) globally; 0 TSX edits
},
fontSize: {
  '11': ['var(--type-caption)', { lineHeight: 'var(--leading-caption)' }],
},
```

The `fontWeight.black` override routes every existing `font-black` utility through `var(--weight-heading)` (900) automatically — same zero-TSX-edits strategy used in Phase 3 for spacing. The `fontSize['11']` key replaces all `text-[11px]` and `text-[10px]` arbitrary values with a semantic utility.

### `.aira-chip` / `.pro-kicker` Migration

`globals.css` class rule migrated: `font-size: 0.68rem` → `font-size: var(--type-caption)` and `font-weight: 800` → `font-weight: var(--weight-heading)`. This is an accessibility fix (0.68rem = ~11px floor) and a token correctness fix (800 had no token; actual heading weight is 900 via `--weight-heading`).

### Component Migration Summary

| Pattern | Token(s) applied | Instance count |
|---|---|---|
| `text-[11px]` / `text-[10px]` badge/pill | `text-11` | 16 |
| `tracking-wide` on ALL-CAPS small text | `tracking-[var(--tracking-label)]` | 14 |
| `rounded-2xl` on semantic components | `rounded-[var(--radius-2xl)]` | 28 |
| `border-[color-mix(in_srgb,var(--danger)_34%,transparent)]` | `border-[var(--danger-border)]` | 17 |
| `border-[color-mix(in_srgb,var(--warning)_34%,transparent)]` | `border-[var(--warning-border)]` | 4 |
| `border-[color-mix(in_srgb,var(--accent)_22%,transparent)]` | `border-[var(--accent-border)]` | 1 |
| `leading-5` / `leading-6` on alert/pre text | `leading-[var(--leading-alert)]` / `leading-[var(--leading-code)]` | 14 |
| `text-white` on solid warning buttons | `text-[var(--on-warning)]` | 3 |

**Files touched:** `globals.css`, `tailwind.config.ts`, `components/ui/tokens.ts`, `components/ui/primitives.tsx`, `components/nav.tsx`, `components/technical-details.tsx`, `components/assistant-answer.tsx`, `app/approvals/page.tsx`, `app/workflows/page.tsx`, `app/workflows/[run_id]/page.tsx`, `app/settings/page.tsx`, `app/tools/page.tsx`, `app/agents/page.tsx`, `app/history/page.tsx`, `app/documents/page.tsx`, `app/overview/page.tsx`, `app/chat/page.tsx`

### Documented Exceptions (Phase 4)

- **`py-0.5` (2px)** — badge/pill vertical padding below token floor. Sub-minimum intentional exception; no `--space-0-5` token introduced.
- **`rounded-xl`** on `assistant-answer.tsx` AnswerCodeBlock — semantic chat answer block, not a Priority 1 pre element. Intentionally excluded from `--radius-2xl` migration.
- **`bg-[color-mix(in_srgb,var(--accent)_6%,transparent)]`** on code block backgrounds — no `--accent-bg-soft` token approved; kept as raw recipe.
- **`--on-danger`** — token defined and available; 0 callsites consumed in Phase 4. All danger buttons in Priority 1 scope use bordered style (`text-[var(--danger)]` on soft background), not solid-danger-fill. Token reserved for future solid-danger button patterns.
- **`operator/page.tsx` dense list `text-[11px]`** — not Priority 1 scope; deferred.

### Deferred Items (Technical Debt)

- **TD-011** — `app/globals.css` `pre { color: #e5edf8; }` hardcoded hex; no `--code-text` token. Target: Phase 5.
- **TD-012** — `color-mix(in srgb, var(--success) 34%, transparent)` raw recipe in 4 files; no `--success-border` token. Target: Phase 5.

### Delivery Record

**Steps 1–9** — Token layer (`globals.css`), Tailwind config, and 15 component/page files migrated per approved plan. Build: `tsc --noEmit` clean, `eslint` 0 errors (22 pre-existing warnings in untouched files), Next.js build 14/14 routes.

**Visual QA** — all screens approved by team review on `feat/command-theme` branch.

---

## Phase 5 — Motion System

### Governance Rules

1. **Single responsibility** — only `transition-duration`, `transition-timing-function`, `transform` (lift/scale), and `animation` values are in scope. No color changes, no new layout tokens, no component restructuring.
2. **No new tokens without approval** — the 5 duration primitives below are frozen. Any new easing curve requires explicit sign-off.
3. **Lift constraint** — maximum hover lift is **1px** (`-translate-y-px`). Values of `hover:-translate-y-0.5` (2px) and `group-hover:-translate-y-1` (4px) are disallowed. Swept and resolved in Phase 5.
4. **Press states** — `active:scale-[0.985]` is required on all interactive button and `<Link>` elements. Nav sidebar `NavLink` items are explicitly excluded (they have their own active treatment in CSS).
5. **Reduced-motion** — `prefers-reduced-motion: reduce` block is required in globals.css; spinner falls back to opacity pulse, not spin.

### Duration Tokens

Added to `:root` in `frontend/app/globals.css`.

| Token | Value | Use case |
|---|---|---|
| `--duration-instant` | `80ms` | Tooltip show/hide, focus rings |
| `--duration-fast` | `120ms` | Buttons, links, chips, icon buttons |
| `--duration-base` | `180ms` | Form inputs, selects, dropdowns |
| `--duration-moderate` | `250ms` | Panels, drawers, accordions |
| `--duration-slow` | `350ms` | Page-level transitions, modals |

### Easing Tokens (updated)

| Token | Value | Status |
|---|---|---|
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | Active |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Active — `--transition-slow` only |
| `--ease-in-out` | *(removed)* | Removed in Phase 5 — no callsites |

### Composite Transition Tokens (updated)

These reference the duration primitives:

| Token | Value |
|---|---|
| `--transition-fast` | `var(--duration-fast) var(--ease-out)` |
| `--transition-base` | `var(--duration-base) var(--ease-out)` |
| `--transition-slow` | `var(--duration-slow) var(--ease-spring)` |

### Tailwind Config Additions (Phase 5)

```typescript
// frontend/tailwind.config.ts — inside extend:
transitionDuration: {
  'instant':  'var(--duration-instant)',
  'fast':     'var(--duration-fast)',
  'base':     'var(--duration-base)',
  'moderate': 'var(--duration-moderate)',
  'slow':     'var(--duration-slow)',
},
```

Usage: `transition duration-fast`, `transition duration-base` — always pair `transition` with an explicit `duration-*`.

### Press States

All interactive buttons and `<Link>` elements receive `active:scale-[0.985]`.

**Exclusions:**
- Nav sidebar `NavLink` items — they have a dedicated CSS active state; scaling would conflict.
- Non-interactive elements with lift (e.g., `<article>` hover cards) — lift fix only, no scale.

### Lift Constraint

| Old (disallowed) | New (approved) |
|---|---|
| `hover:-translate-y-0.5` (2px) | `hover:-translate-y-px` (1px) |
| `group-hover:-translate-y-1` (4px) | `group-hover:-translate-y-px` (1px) |

### Reduced-Motion Spinner

```css
@media (prefers-reduced-motion: reduce) {
  .animate-spin {
    animation: spinner-pulse 2s ease-in-out infinite !important;
  }
}
@keyframes spinner-pulse {
  0%, 100% { opacity: 0.3; }
  50%       { opacity: 1; }
}
```

Replaces continuous rotation with an opacity pulse for users who have motion sensitivity enabled.

### Dead Keyframes Removed

The following `@keyframes` had zero callsites and were removed from `globals.css`:

- `pageFade`
- `handshake`
- `chatBubblePop`

The duplicate `@keyframes fadeUp` in `chat/chat.css` (8px translateY) was also removed. The canonical definition in `globals.css` (12px translateY) is used by `.chat-message { animation: fadeUp 0.25s ease; }`.

### Migration Summary

| Pattern | Tailwind utility | Files affected |
|---|---|---|
| Bare `transition` on buttons/links | `transition duration-fast active:scale-[0.985]` | 12 |
| Bare `transition` on inputs/selects | `transition duration-base` | 6 |
| `hover:-translate-y-0.5` lift violations | `hover:-translate-y-px` | 5 |
| `group-hover:-translate-y-1` lift violations | `group-hover:-translate-y-px` | 2 |
| Nav logo `<Link>` | `transition-all duration-200 hover:-translate-y-px active:scale-[0.985]` | 1 |

**Files touched:** `globals.css`, `tailwind.config.ts`, `components/ui/tokens.ts`, `components/ui/primitives.tsx`, `components/nav.tsx`, `components/citation-list.tsx`, `components/time-theme-control.tsx`, `app/approvals/page.tsx`, `app/workflows/page.tsx`, `app/workflows/[run_id]/page.tsx`, `app/settings/page.tsx`, `app/tools/page.tsx`, `app/agents/page.tsx`, `app/history/page.tsx`, `app/documents/page.tsx`, `app/overview/page.tsx`, `app/operator/page.tsx`, `app/upload/page.tsx`, `app/chat/chat.css`
