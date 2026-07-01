# AIRA-X Design System

## Phase Status

| Phase | Scope | Status |
|---|---|---|
| Phase 1 | Surface contract (8 tokens) + radius scale | **Frozen** |
| Phase 2 | Typography contract (12 size + 7 weight + 5 leading + 5 tracking tokens) + 13 utility classes | **Frozen** |
| Phase 3 | Color token migration (raw Tailwind → semantic vars); button/component tokens; `font-bold` weight gap | Pending |
| Phase 4 | Component polish; badge/pill refactor; `<pre>` block tokens; form input tokens | Pending |

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

Each theme block (`[data-theme="*"]`) overrides all 8 tokens. Back-compat aliases (`--surface`, `--surface-soft`, `--surface-muted`, `--surface-strong`) point to nearest new tokens and will be removed in Phase 3.

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

Phase 3 will migrate the 14 `border-radius: var(--radius-*)` consumer rules in `globals.css` to the new names.

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

**Gap (TD-004):** `font-bold` (700) has no canonical token. Affects `aira-chip` text, nav link labels, operator section headers (post-redesign), error/flash feedback text. Target: Phase 3.

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
