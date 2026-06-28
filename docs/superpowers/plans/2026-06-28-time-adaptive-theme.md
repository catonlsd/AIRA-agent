# Time-Adaptive Theme System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AIRA-X's manual light/dark/system theme toggle with an automatic, clock-driven 6-period theme (predawn→night) that applies app-wide with smooth crossfades, plus an Auto + per-period manual override in Settings.

**Architecture:** A pure `lib/timeTheme.ts` engine buckets the local clock into 6 periods and computes the ms to the next boundary. A rewritten `theme-provider.tsx` sets `data-theme="<period>"` on `<html>` (override-or-auto), self-reschedules at boundaries, and re-syncs on focus. `app/globals.css` maps each period's palette onto AIRA-X's existing ~30-token contract; components are untouched because they already consume those tokens. A blocking inline script in `layout.tsx` sets the theme before first paint to avoid a flash.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind (arbitrary `[var()]` values), CSS custom properties, lucide-react, Node's built-in test runner (`node --test`).

## Global Constraints

- **Frontend-only.** No backend, route, API, or product-feature changes.
- **Status colors are a regression-wall guarantee:** `--success/--warning/--danger/--info/--alert` stay semantic, decoupled from accent, pinned per background family (see Task 2). Never derive them from the accent.
- **Tokens are the only color source.** Components consume the existing contract (`--surface*`, `--text*`, `--border*`, `--accent*`, `--secondary*`, status, shadows). Do **not** add hardcoded colors to components.
- **`useTheme` keeps its name and path** (`components/theme-provider.tsx`) — only its shape changes.
- **localStorage key stays `"aira-x-theme"`.** Legacy values (`"light"/"dark"/"system"`) must be treated as Auto, never crash.
- **Gradient = v1 swap only.** No 2-layer crossfade.
- **Regression wall stays green:** `npx tsc --noEmit`, `npm run lint` (no new errors), `npm run build`, `npm run e2e` (6 specs), `npm test` (existing 104 + new engine tests).
- **WCAG carry-forward (Task 2):** the sunrise block must carry inline AA contrast ratios for `--text-muted` and `--text-subtle` against `--bg`; fix any value below 4.5:1 before committing.
- All work on branch `feat/command-theme`. Run all commands from `D:\AIRA-agent\frontend`.

---

### Task 1: Theme engine + unit tests

**Files:**
- Create: `frontend/lib/timeTheme.ts`
- Test: `frontend/lib/timeTheme.test.mts`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `type ThemeName = "predawn" | "sunrise" | "daytime" | "dusk" | "sunset" | "night"`
  - `const THEME_NAMES: readonly ThemeName[]` (ordered predawn→night)
  - `const THEME_LABELS: Record<ThemeName, string>`
  - `function isThemeName(value: unknown): value is ThemeName`
  - `function getThemeForTime(date?: Date): ThemeName`
  - `function msUntilNextTheme(date?: Date): number`

- [ ] **Step 1: Write the failing test** — create `frontend/lib/timeTheme.test.mts`:

```ts
// Pure-logic tests for the time-adaptive theme engine. Node's built-in runner, no deps.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getThemeForTime,
  msUntilNextTheme,
  isThemeName,
  THEME_NAMES,
  THEME_LABELS,
} from "./timeTheme.ts";

const at = (h: number, m: number, s = 0) => new Date(2026, 0, 1, h, m, s);

test("getThemeForTime maps every segment incl. boundaries", () => {
  assert.equal(getThemeForTime(at(2, 59)), "night");
  assert.equal(getThemeForTime(at(3, 0)), "predawn");
  assert.equal(getThemeForTime(at(5, 29)), "predawn");
  assert.equal(getThemeForTime(at(5, 30)), "sunrise");
  assert.equal(getThemeForTime(at(7, 59)), "sunrise");
  assert.equal(getThemeForTime(at(8, 0)), "daytime");
  assert.equal(getThemeForTime(at(16, 59)), "daytime");
  assert.equal(getThemeForTime(at(17, 0)), "dusk");
  assert.equal(getThemeForTime(at(18, 29)), "dusk");
  assert.equal(getThemeForTime(at(18, 30)), "sunset");
  assert.equal(getThemeForTime(at(19, 14)), "sunset");
  assert.equal(getThemeForTime(at(19, 15)), "night");
  assert.equal(getThemeForTime(at(23, 59)), "night");
  assert.equal(getThemeForTime(at(0, 0)), "night");
});

test("msUntilNextTheme returns ms to the next boundary", () => {
  assert.equal(msUntilNextTheme(at(2, 0, 0)), 60 * 60 * 1000); // → 03:00
  assert.equal(msUntilNextTheme(at(4, 0, 0)), 90 * 60 * 1000); // → 05:30
  assert.equal(msUntilNextTheme(at(7, 59, 30)), 30 * 1000); // → 08:00
});

test("msUntilNextTheme wraps past the last boundary to tomorrow 03:00", () => {
  assert.equal(msUntilNextTheme(at(20, 0, 0)), 7 * 60 * 60 * 1000); // 20:00 → 03:00 next day
  assert.equal(msUntilNextTheme(at(0, 0, 0)), 3 * 60 * 60 * 1000); // 00:00 → 03:00 same day
});

test("isThemeName validates and rejects legacy values", () => {
  assert.equal(isThemeName("daytime"), true);
  assert.equal(isThemeName("night"), true);
  assert.equal(isThemeName("dark"), false);
  assert.equal(isThemeName("system"), false);
  assert.equal(isThemeName(null), false);
  assert.equal(isThemeName(42), false);
});

test("THEME_NAMES and THEME_LABELS cover all six periods", () => {
  assert.equal(THEME_NAMES.length, 6);
  for (const name of THEME_NAMES) {
    assert.equal(typeof THEME_LABELS[name], "string");
  }
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test`
Expected: FAIL — `Cannot find module './timeTheme.ts'` (file not created yet).

- [ ] **Step 3: Write the minimal implementation** — create `frontend/lib/timeTheme.ts`:

```ts
// Time-adaptive theme engine. Pure + DOM-free so it is fully unit-testable.
// The 24h clock is bucketed into 6 named periods; the provider applies the result
// as data-theme="<name>" on <html>.

export type ThemeName =
  | "predawn"
  | "sunrise"
  | "daytime"
  | "dusk"
  | "sunset"
  | "night";

export const THEME_NAMES: readonly ThemeName[] = [
  "predawn",
  "sunrise",
  "daytime",
  "dusk",
  "sunset",
  "night",
] as const;

export const THEME_LABELS: Record<ThemeName, string> = {
  predawn: "Pre-dawn",
  sunrise: "Sunrise",
  daytime: "Daytime",
  dusk: "Dusk",
  sunset: "Sunset",
  night: "Night",
};

export function isThemeName(value: unknown): value is ThemeName {
  return (
    typeof value === "string" &&
    (THEME_NAMES as readonly string[]).includes(value)
  );
}

/** Period for the given local time. `night` is the fallback (wraps midnight). */
export function getThemeForTime(date: Date = new Date()): ThemeName {
  const totalMinutes = date.getHours() * 60 + date.getMinutes();
  if (totalMinutes >= 180 && totalMinutes <= 329) return "predawn"; // 03:00–05:29
  if (totalMinutes >= 330 && totalMinutes <= 479) return "sunrise"; // 05:30–07:59
  if (totalMinutes >= 480 && totalMinutes <= 1019) return "daytime"; // 08:00–16:59
  if (totalMinutes >= 1020 && totalMinutes <= 1109) return "dusk"; // 17:00–18:29
  if (totalMinutes >= 1110 && totalMinutes <= 1154) return "sunset"; // 18:30–19:14
  return "night"; // 19:15–02:59
}

/** Milliseconds until the next period boundary (drives a self-rescheduling timeout). */
export function msUntilNextTheme(date: Date = new Date()): number {
  const totalSeconds =
    date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds();
  const boundaries = [
    3 * 3600, // 03:00
    5 * 3600 + 30 * 60, // 05:30
    8 * 3600, // 08:00
    17 * 3600, // 17:00
    18 * 3600 + 30 * 60, // 18:30
    19 * 3600 + 15 * 60, // 19:15
  ];
  const daySeconds = 24 * 3600;
  for (const b of boundaries) {
    if (totalSeconds < b) return (b - totalSeconds) * 1000;
  }
  return (daySeconds - totalSeconds + 3 * 3600) * 1000; // tomorrow 03:00
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test`
Expected: PASS — all new `timeTheme` tests green, existing 104 still green.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/timeTheme.ts frontend/lib/timeTheme.test.mts
git commit -m "feat(theme): time-adaptive theme engine (6-period clock buckets)"
```

---

### Task 2: Token blocks, transitions, gradient layer (`app/globals.css`)

**Files:**
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `data-theme="<period>"` set on `<html>` by the provider (Task 3). Until Task 3 lands, `:root` (night) is the rendered default — that is intended and keeps the app working.
- Produces: a complete per-period mapping of every token components already use, plus new `--bg-gradient`, `--scrollbar-thumb`, `--scrollbar-track`.

**Recipe (applies to every period block below):** existing tokens are mapped from each period's palette; `color-mix()` (already used in this file) derives the in-between steps. Status colors are pinned (not derived). Light periods use `color-scheme: light`; `night` uses `dark`.

- [ ] **Step 1: Replace the `:root` token block with the `night` palette as the no-JS/SSR default.**

In `frontend/app/globals.css`, replace the entire `:root { … }` design-tokens block (currently the dark palette at the top, ~lines 16–135, ending before the first `[data-theme=...]` selector) with:

```css
:root {
  color-scheme: dark;

  /* === NIGHT (also the SSR / no-JS default) === */
  --bg: #2e2c7a;
  --bg-gradient: #2e2c7a; /* solid — night has no gradient */
  --bg-muted: rgba(60, 58, 130, 0.75);
  --bg-elevated: rgba(50, 48, 110, 0.9);

  --surface: rgba(50, 48, 110, 0.9);
  --surface-soft: color-mix(in srgb, var(--surface) 86%, #ffffff 14%);
  --surface-muted: rgba(60, 58, 130, 0.75);
  --surface-hover: rgba(255, 255, 255, 0.06);
  --surface-strong: #323070;

  --text-strong: #e8e6ff;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #a89fcc;
  --text-subtle: color-mix(in srgb, var(--text-muted) 70%, transparent);

  --border: rgba(255, 255, 255, 0.1);
  --border-strong: rgba(255, 255, 255, 0.28);

  --accent: #9fa8da;
  --accent-strong: #c5cae9;
  --accent-soft: rgba(159, 168, 218, 0.12);
  --accent-foreground: #1a1850;
  --accent-glow: rgba(255, 255, 255, 0.06);

  --secondary: #b0a8ff;
  --secondary-soft: color-mix(in srgb, var(--secondary) 12%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);

  /* status — night (bright "400" shades on deep indigo) */
  --success: #34d399;
  --success-soft: color-mix(in srgb, #34d399 12%, transparent);
  --warning: #fbbf24;
  --warning-soft: color-mix(in srgb, #fbbf24 12%, transparent);
  --danger: #f87171;
  --danger-soft: color-mix(in srgb, #f87171 12%, transparent);
  --info: #60a5fa;
  --info-soft: color-mix(in srgb, #60a5fa 12%, transparent);
  --alert: #fb923c;
  --alert-soft: color-mix(in srgb, #fb923c 12%, transparent);

  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.35);
  --shadow-soft: 0 4px 16px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.04);
  --shadow-card: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 4px 16px rgba(0, 0, 0, 0.45);
  --shadow-hover: 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent), 0 14px 36px -16px rgba(0, 0, 0, 0.62);
  --shadow-glow: 0 0 0 1px color-mix(in srgb, var(--accent) 22%, transparent), 0 0 32px color-mix(in srgb, var(--accent) 14%, transparent);
  --shadow-panel: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 10px 30px -14px rgba(0, 0, 0, 0.58);

  --scrollbar-thumb: #5c5a8e;
  --scrollbar-track: #252360;
}
```

> Note: keep any **non-color** tokens that lived in the old `:root` (radii, `--transition-*`, `--ease-*`, `--font-*`, `--radius-*`, `--grid-line`, `--page-vignette`, `--octa-*`, `--pre-bg`). Do not delete those — only the color palette is being replaced. If they sat inside the same `:root` block, leave them in place below the palette.

- [ ] **Step 2: Add the 6 `[data-theme]` period blocks.** Immediately after `:root`, **remove the now-dead `[data-theme="dark"]` and `[data-theme="light"]` blocks** and any `[data-aira-mode="aira"]`/`[data-aira-mode="aira-x"]` blocks that override `--accent*` (the accent must come from the period). Then insert:

```css
/* ============ TIME-ADAPTIVE PERIODS ============ */

[data-theme="predawn"] {
  color-scheme: light;
  --bg: #e2d0f8;
  --bg-gradient: linear-gradient(160deg, #f5eeff 0%, #e2d0f8 50%, #d4bff2 100%);
  --bg-muted: rgba(225, 210, 248, 0.6);
  --bg-elevated: rgba(240, 230, 255, 0.75);
  --surface: rgba(240, 230, 255, 0.75);
  --surface-soft: color-mix(in srgb, var(--surface) 88%, #ffffff 12%);
  --surface-muted: rgba(225, 210, 248, 0.6);
  --surface-hover: rgba(139, 92, 246, 0.12);
  --surface-strong: #f0e8ff;
  --text-strong: #3b1f6b;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #6b4fa0;
  --text-subtle: color-mix(in srgb, var(--text-muted) 75%, var(--text-strong));
  --border: rgba(139, 92, 246, 0.18);
  --border-strong: rgba(139, 92, 246, 0.45);
  --accent: #7c3aed;
  --accent-strong: #6d28d9;
  --accent-soft: rgba(124, 58, 237, 0.1);
  --accent-foreground: #ffffff;
  --accent-glow: rgba(139, 92, 246, 0.12);
  --secondary: #4040c0;
  --secondary-soft: color-mix(in srgb, var(--secondary) 12%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #047857; --success-soft: color-mix(in srgb, #047857 12%, transparent);
  --warning: #b45309; --warning-soft: color-mix(in srgb, #b45309 12%, transparent);
  --danger: #b91c1c; --danger-soft: color-mix(in srgb, #b91c1c 12%, transparent);
  --info: #0369a1; --info-soft: color-mix(in srgb, #0369a1 12%, transparent);
  --alert: #c2410c; --alert-soft: color-mix(in srgb, #c2410c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(100, 60, 200, 0.1);
  --shadow-soft: 0 4px 16px rgba(100, 60, 200, 0.15);
  --shadow-card: 0 1px 2px rgba(100, 60, 200, 0.12), 0 10px 30px -14px rgba(100, 60, 200, 0.25);
  --scrollbar-thumb: #c4a8f0;
  --scrollbar-track: #ede5ff;
}

[data-theme="sunrise"] {
  color-scheme: light;
  --bg: #ffd54f;
  --bg-gradient: linear-gradient(160deg, #ffe082 0%, #ffd54f 40%, #ffca28 100%);
  --bg-muted: rgba(255, 220, 150, 0.65);
  --bg-elevated: rgba(255, 235, 180, 0.8);
  --surface: rgba(255, 235, 180, 0.8);
  --surface-soft: color-mix(in srgb, var(--surface) 88%, #ffffff 12%);
  --surface-muted: rgba(255, 220, 150, 0.65);
  --surface-hover: rgba(233, 30, 140, 0.1);
  --surface-strong: #fff3d6;
  --text-strong: #6b1a3a;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #9c2865; /* on --bg #ffd54f → 5.12:1 (WCAG AA pass) */
  --text-subtle: #8c2454; /* darkened override; on --bg #ffd54f → 5.96:1 (AA pass).
                             The generic transparent-fade recipe would give ~2.9:1 (FAIL),
                             so this period pins an explicit dark subtle. */
  --border: rgba(233, 30, 140, 0.18);
  --border-strong: rgba(233, 30, 140, 0.45);
  --accent: #e91e8c;
  --accent-strong: #c2185b;
  --accent-soft: rgba(233, 30, 140, 0.1);
  --accent-foreground: #ffffff;
  --accent-glow: rgba(233, 30, 140, 0.1);
  --secondary: #6b21a8;
  --secondary-soft: color-mix(in srgb, var(--secondary) 12%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #047857; --success-soft: color-mix(in srgb, #047857 12%, transparent);
  --warning: #b45309; --warning-soft: color-mix(in srgb, #b45309 12%, transparent);
  --danger: #b91c1c; --danger-soft: color-mix(in srgb, #b91c1c 12%, transparent);
  --info: #0369a1; --info-soft: color-mix(in srgb, #0369a1 12%, transparent);
  --alert: #c2410c; --alert-soft: color-mix(in srgb, #c2410c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(180, 80, 20, 0.12);
  --shadow-soft: 0 4px 16px rgba(180, 80, 20, 0.18);
  --shadow-card: 0 1px 2px rgba(180, 80, 20, 0.14), 0 10px 30px -14px rgba(180, 80, 20, 0.28);
  --scrollbar-thumb: #f48fb1;
  --scrollbar-track: #fff9c4;
}

[data-theme="daytime"] {
  color-scheme: light;
  --bg: #e3f2fd;
  --bg-gradient: linear-gradient(160deg, #ffffff 0%, #e3f2fd 50%, #bbdefb 100%);
  --bg-muted: rgba(232, 244, 253, 0.7);
  --bg-elevated: rgba(255, 255, 255, 0.9);
  --surface: rgba(255, 255, 255, 0.9);
  --surface-soft: color-mix(in srgb, var(--surface) 92%, #ffffff 8%);
  --surface-muted: rgba(232, 244, 253, 0.7);
  --surface-hover: rgba(21, 101, 192, 0.08);
  --surface-strong: #ffffff;
  --text-strong: #0d2b5e;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #1565c0;
  --text-subtle: color-mix(in srgb, var(--text-muted) 72%, var(--text-strong));
  --border: rgba(21, 101, 192, 0.15);
  --border-strong: rgba(21, 101, 192, 0.4);
  --accent: #1976d2;
  --accent-strong: #1565c0;
  --accent-soft: rgba(25, 118, 210, 0.08);
  --accent-foreground: #ffffff;
  --accent-glow: rgba(21, 101, 192, 0.08);
  --secondary: #42a5f5;
  --secondary-soft: color-mix(in srgb, var(--secondary) 14%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #047857; --success-soft: color-mix(in srgb, #047857 12%, transparent);
  --warning: #b45309; --warning-soft: color-mix(in srgb, #b45309 12%, transparent);
  --danger: #b91c1c; --danger-soft: color-mix(in srgb, #b91c1c 12%, transparent);
  --info: #0369a1; --info-soft: color-mix(in srgb, #0369a1 12%, transparent);
  --alert: #c2410c; --alert-soft: color-mix(in srgb, #c2410c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(21, 101, 192, 0.1);
  --shadow-soft: 0 4px 16px rgba(21, 101, 192, 0.14);
  --shadow-card: 0 1px 2px rgba(21, 101, 192, 0.1), 0 10px 30px -14px rgba(21, 101, 192, 0.22);
  --scrollbar-thumb: #90caf9;
  --scrollbar-track: #e3f2fd;
}

[data-theme="dusk"] {
  color-scheme: light;
  --bg: #d6e9f8;
  --bg-gradient: linear-gradient(180deg, #bbdefb 0%, #e3f2fd 45%, #ffe082 75%, #ffd54f 100%);
  --bg-muted: rgba(210, 235, 255, 0.65);
  --bg-elevated: rgba(230, 245, 255, 0.82);
  --surface: rgba(230, 245, 255, 0.82);
  --surface-soft: color-mix(in srgb, var(--surface) 90%, #ffffff 10%);
  --surface-muted: rgba(210, 235, 255, 0.65);
  --surface-hover: rgba(255, 160, 0, 0.1);
  --surface-strong: #eaf4ff;
  --text-strong: #1a3050;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #2e5fa3;
  --text-subtle: color-mix(in srgb, var(--text-muted) 72%, var(--text-strong));
  --border: rgba(21, 101, 192, 0.15);
  --border-strong: rgba(255, 160, 0, 0.45);
  --accent: #0288d1;
  --accent-strong: #0277bd;
  --accent-soft: rgba(2, 136, 209, 0.1);
  --accent-foreground: #ffffff;
  --accent-glow: rgba(255, 160, 0, 0.1);
  --secondary: #ffa000;
  --secondary-soft: color-mix(in srgb, var(--secondary) 14%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #047857; --success-soft: color-mix(in srgb, #047857 12%, transparent);
  --warning: #b45309; --warning-soft: color-mix(in srgb, #b45309 12%, transparent);
  --danger: #b91c1c; --danger-soft: color-mix(in srgb, #b91c1c 12%, transparent);
  --info: #0369a1; --info-soft: color-mix(in srgb, #0369a1 12%, transparent);
  --alert: #c2410c; --alert-soft: color-mix(in srgb, #c2410c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(21, 101, 192, 0.1);
  --shadow-soft: 0 4px 16px rgba(21, 101, 192, 0.15);
  --shadow-card: 0 1px 2px rgba(21, 101, 192, 0.1), 0 10px 30px -14px rgba(21, 101, 192, 0.24);
  --scrollbar-thumb: #90caf9;
  --scrollbar-track: #e3f2fd;
}

[data-theme="sunset"] {
  color-scheme: light;
  --bg: #f3c8d8;
  --bg-gradient: linear-gradient(160deg, #e8d5f5 0%, #f3b8d0 40%, #ffb74d 100%);
  --bg-muted: rgba(235, 208, 242, 0.65);
  --bg-elevated: rgba(245, 225, 248, 0.8);
  --surface: rgba(245, 225, 248, 0.8);
  --surface-soft: color-mix(in srgb, var(--surface) 88%, #ffffff 12%);
  --surface-muted: rgba(235, 208, 242, 0.65);
  --surface-hover: rgba(224, 64, 251, 0.1);
  --surface-strong: #f7e9fa;
  --text-strong: #4a1560;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #9c27b0;
  --text-subtle: color-mix(in srgb, var(--text-muted) 75%, var(--text-strong));
  --border: rgba(224, 64, 251, 0.18);
  --border-strong: rgba(224, 64, 251, 0.42);
  --accent: #ab47bc;
  --accent-strong: #8e24aa;
  --accent-soft: rgba(171, 71, 188, 0.1);
  --accent-foreground: #ffffff;
  --accent-glow: rgba(224, 64, 251, 0.1);
  --secondary: #ff7043;
  --secondary-soft: color-mix(in srgb, var(--secondary) 14%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #047857; --success-soft: color-mix(in srgb, #047857 12%, transparent);
  --warning: #b45309; --warning-soft: color-mix(in srgb, #b45309 12%, transparent);
  --danger: #b91c1c; --danger-soft: color-mix(in srgb, #b91c1c 12%, transparent);
  --info: #0369a1; --info-soft: color-mix(in srgb, #0369a1 12%, transparent);
  --alert: #c2410c; --alert-soft: color-mix(in srgb, #c2410c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(150, 40, 180, 0.1);
  --shadow-soft: 0 4px 16px rgba(150, 40, 180, 0.18);
  --shadow-card: 0 1px 2px rgba(150, 40, 180, 0.12), 0 10px 30px -14px rgba(150, 40, 180, 0.26);
  --scrollbar-thumb: #ce93d8;
  --scrollbar-track: #f3e5f5;
}

[data-theme="night"] {
  color-scheme: dark;
  --bg: #2e2c7a;
  --bg-gradient: #2e2c7a;
  --bg-muted: rgba(60, 58, 130, 0.75);
  --bg-elevated: rgba(50, 48, 110, 0.9);
  --surface: rgba(50, 48, 110, 0.9);
  --surface-soft: color-mix(in srgb, var(--surface) 86%, #ffffff 14%);
  --surface-muted: rgba(60, 58, 130, 0.75);
  --surface-hover: rgba(255, 255, 255, 0.06);
  --surface-strong: #323070;
  --text-strong: #e8e6ff;
  --text: color-mix(in srgb, var(--text-strong) 82%, var(--text-muted));
  --text-muted: #a89fcc;
  --text-subtle: color-mix(in srgb, var(--text-muted) 70%, transparent);
  --border: rgba(255, 255, 255, 0.1);
  --border-strong: rgba(255, 255, 255, 0.28);
  --accent: #9fa8da;
  --accent-strong: #c5cae9;
  --accent-soft: rgba(159, 168, 218, 0.12);
  --accent-foreground: #1a1850;
  --accent-glow: rgba(255, 255, 255, 0.06);
  --secondary: #b0a8ff;
  --secondary-soft: color-mix(in srgb, var(--secondary) 12%, transparent);
  --secondary-glow: color-mix(in srgb, var(--secondary) 10%, transparent);
  --success: #34d399; --success-soft: color-mix(in srgb, #34d399 12%, transparent);
  --warning: #fbbf24; --warning-soft: color-mix(in srgb, #fbbf24 12%, transparent);
  --danger: #f87171; --danger-soft: color-mix(in srgb, #f87171 12%, transparent);
  --info: #60a5fa; --info-soft: color-mix(in srgb, #60a5fa 12%, transparent);
  --alert: #fb923c; --alert-soft: color-mix(in srgb, #fb923c 12%, transparent);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.35);
  --shadow-soft: 0 4px 16px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.04);
  --shadow-card: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 4px 16px rgba(0, 0, 0, 0.45);
  --scrollbar-thumb: #5c5a8e;
  --scrollbar-track: #252360;
}
```

- [ ] **Step 3: Replace the body background rules with the gradient layer.** Find the existing `body` background rules and the flat-dark overrides (search the file for `body {`, `body::before`, `body::after`, and `html[data-theme="dark"] body`). Replace those background-related rules with:

```css
body {
  min-height: 100dvh;
  background: var(--bg);
  color: var(--text);
}

/* Fixed full-viewport gradient layer (period background). v1 swaps at boundaries. */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -1;
  background: var(--bg-gradient);
  pointer-events: none;
}

body::after {
  display: none;
}
```

> Remove the earlier `html[data-theme="dark"] body::before { display: none; }`, the vignette `body::after` rule, and any `html[data-theme="dark"] body { background: var(--bg); }` override — they are superseded by the rules above. Keep `.no-page-scroll`, `.layout-root`, `.layout-sidebar`, `.layout-main`, `.scroll-region` and all other layout utilities untouched.

- [ ] **Step 4: Add the smooth-transition rules.** Append near the top-level base layer (after the body rules):

```css
/* Smooth crossfade on every theme switch (gradient itself swaps — v1). */
*,
*::before,
*::after {
  transition:
    background-color 800ms cubic-bezier(0.4, 0, 0.2, 1),
    border-color 800ms cubic-bezier(0.4, 0, 0.2, 1),
    color 800ms cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 800ms ease;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    transition: none !important;
  }
}
```

- [ ] **Step 5: Wire the scrollbar tokens.** Find the existing `::-webkit-scrollbar-thumb` / `::-webkit-scrollbar-track` (or `* { scrollbar-color: … }`) rules and set them to the tokens:

```css
* {
  scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
}
::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
}
::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}
```

- [ ] **Step 6: Verify the build compiles the CSS.**

Run: `npm run build`
Expected: build succeeds (CSS is valid; `color-mix` is supported). If it fails, read the error and fix the offending rule.

- [ ] **Step 7: Contrast audit (WCAG carry-forward).** For **each light period** (predawn, sunrise, daytime, dusk, sunset), compute the contrast ratio of the effective `--text-muted` and `--text-subtle` against that period's `--bg` (solid). The sunrise block already carries its ratios inline (`--text-muted` 5.12:1, `--text-subtle` 5.96:1). Confirm the others are ≥ 4.5:1; if any falls below, pin an explicit darker `--text-subtle`/`--text-muted` for that period (mix further toward `--text-strong`) and re-check. Record the final sunrise ratios in the commit body.

> Reference (sRGB relative luminance, AA threshold 4.5:1). Quick check command (optional helper, scratchpad only):
> `node -e "const L=h=>{const c=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255).map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4);return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]};const cr=(a,b)=>{const x=L(a),y=L(b);return ((Math.max(x,y)+0.05)/(Math.min(x,y)+0.05)).toFixed(2)};console.log('muted',cr('#9C2865','#FFD54F'),'subtle',cr('#8C2454','#FFD54F'))"`
> (`color-mix` for `--text` need not be audited — it is heavier than muted, so it always passes when muted does.)

- [ ] **Step 8: Commit**

```bash
git add frontend/app/globals.css
git commit -m "feat(theme): 6 period token blocks, gradient layer, crossfade transitions

night is the :root/SSR default. Status colors pinned per bg family.
Sunrise AA: --text-muted 5.12:1, --text-subtle 5.96:1 vs --bg."
```

---

### Task 3: Provider rewrite, anti-flash script, Settings control (atomic compiling change)

This task is one unit because the new provider API breaks the old `theme-toggle.tsx` at compile time; the toggle must be replaced in the same commit.

**Files:**
- Modify (rewrite): `frontend/components/theme-provider.tsx`
- Create: `frontend/components/time-theme-control.tsx`
- Delete: `frontend/components/theme-toggle.tsx`
- Modify: `frontend/app/settings/page.tsx` (swap import + usage)
- Modify: `frontend/app/layout.tsx` (anti-flash inline script; `themeColor` default)

**Interfaces:**
- Consumes (from Task 1): `getThemeForTime`, `msUntilNextTheme`, `isThemeName`, `THEME_NAMES`, `THEME_LABELS`, `ThemeName`.
- Produces: `useTheme(): { theme: ThemeName; autoTheme: ThemeName; isAuto: boolean; setOverride(name: ThemeName | null): void }` and `<TimeThemeControl />`.

- [ ] **Step 1: Rewrite `frontend/components/theme-provider.tsx`:**

```tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getThemeForTime,
  isThemeName,
  msUntilNextTheme,
  type ThemeName,
} from "@/lib/timeTheme";

const STORAGE_KEY = "aira-x-theme";

type ThemeContextValue = {
  theme: ThemeName;
  autoTheme: ThemeName;
  isAuto: boolean;
  setOverride: (name: ThemeName | null) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readOverride(): ThemeName | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isThemeName(value) ? value : null; // legacy light/dark/system → Auto
  } catch {
    return null;
  }
}

function applyTheme(name: ThemeName) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = name;
  root.style.colorScheme = name === "night" ? "dark" : "light";

  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (meta && bg) meta.content = bg;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [autoTheme, setAutoTheme] = useState<ThemeName>(() => getThemeForTime());
  const [override, setOverrideState] = useState<ThemeName | null>(null);

  // Server render had no storage access; hydrate the override after mount.
  useEffect(() => {
    setOverrideState(readOverride());
    setAutoTheme(getThemeForTime());
  }, []);

  const activeTheme = override ?? autoTheme;

  useEffect(() => {
    applyTheme(activeTheme);
  }, [activeTheme]);

  // Self-rescheduling boundary timer (no polling).
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setAutoTheme(getThemeForTime());
        schedule();
      }, msUntilNextTheme());
    };
    schedule();
    return () => clearTimeout(timer);
  }, []);

  // Re-sync when the tab regains focus (laptop wake / long idle).
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") setAutoTheme(getThemeForTime());
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);

  const setOverride = useCallback((name: ThemeName | null) => {
    setOverrideState(name);
    try {
      if (name) window.localStorage.setItem(STORAGE_KEY, name);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore storage failures; override still applies in memory.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: activeTheme,
      autoTheme,
      isAuto: override === null,
      setOverride,
    }),
    [activeTheme, autoTheme, override, setOverride],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}
```

- [ ] **Step 2: Create `frontend/components/time-theme-control.tsx`:**

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  CloudSun,
  Moon,
  Sparkles,
  Sun,
  Sunrise,
  Sunset,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";
import { THEME_LABELS, THEME_NAMES, type ThemeName } from "@/lib/timeTheme";

const ICONS: Record<ThemeName, LucideIcon> = {
  predawn: Moon,
  sunrise: Sunrise,
  daytime: Sun,
  dusk: Sunset,
  sunset: CloudSun,
  night: Sparkles,
};

export function TimeThemeControl() {
  const { theme, autoTheme, isAuto, setOverride } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Override is hydrated post-mount; gate active styling to avoid an SSR mismatch.
  useEffect(() => setMounted(true), []);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-1">
        <button
          type="button"
          onClick={() => setOverride(null)}
          aria-pressed={mounted ? isAuto : false}
          className={cn(
            "flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] font-bold transition",
            mounted && isAuto
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
          )}
        >
          Auto
        </button>

        {THEME_NAMES.map((name) => {
          const Icon = ICONS[name];
          const active = mounted && !isAuto && theme === name;

          return (
            <button
              key={name}
              type="button"
              onClick={() => setOverride(name)}
              aria-pressed={active}
              aria-label={`Use ${THEME_LABELS[name]} theme`}
              className={cn(
                "flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-[11px] font-bold transition",
                active
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{THEME_LABELS[name]}</span>
            </button>
          );
        })}
      </div>

      {mounted && isAuto ? (
        <p className="px-1 text-[11px] font-medium text-[var(--text-subtle)]">
          Auto · {THEME_LABELS[autoTheme]} now
        </p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 3: Delete the old toggle**

```bash
git rm frontend/components/theme-toggle.tsx
```

- [ ] **Step 4: Swap the import + usage in `frontend/app/settings/page.tsx`.**
  - Change the import on line 33 from `import { ThemeToggle } from "@/components/theme-toggle";` to `import { TimeThemeControl } from "@/components/time-theme-control";`
  - Change the usage on line 1536 from `<ThemeToggle />` to `<TimeThemeControl />`.

- [ ] **Step 5: Add the anti-flash inline script + default themeColor in `frontend/app/layout.tsx`.**
  - Change `themeColor: "#212121"` to `themeColor: "#2e2c7a"` (night default; the provider updates it live per period).
  - Add a `<head>` with the blocking script **before** `<body>`:

```tsx
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              '(function(){try{var k="aira-x-theme";var v=localStorage.getItem(k);' +
              'var n=["predawn","sunrise","daytime","dusk","sunset","night"];' +
              'var t=n.indexOf(v)>=0?v:null;if(!t){var d=new Date();' +
              'var m=d.getHours()*60+d.getMinutes();' +
              't=(m>=180&&m<=329)?"predawn":(m>=330&&m<=479)?"sunrise":' +
              '(m>=480&&m<=1019)?"daytime":(m>=1020&&m<=1109)?"dusk":' +
              '(m>=1110&&m<=1154)?"sunset":"night";}' +
              'var e=document.documentElement;e.dataset.theme=t;' +
              'e.style.colorScheme=t==="night"?"dark":"light";}catch(e){}})();',
          }}
        />
      </head>
      <body
        className={`${manrope.variable} ${ibmPlexMono.variable} ${jetbrainsMono.variable} no-page-scroll`}
      >
        <ThemeProvider>
          <ModeProvider>
            <AppShell>{children}</AppShell>
          </ModeProvider>
        </ThemeProvider>
      </body>
    </html>
  );
```

- [ ] **Step 6: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors (no remaining references to `ThemeToggle` or the old `setTheme`/`resolvedTheme` API).

- [ ] **Step 7: Lint**

Run: `npm run lint`
Expected: no new errors (pre-existing warnings unchanged).

- [ ] **Step 8: Build**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/theme-provider.tsx frontend/components/time-theme-control.tsx frontend/app/settings/page.tsx frontend/app/layout.tsx
git commit -m "feat(theme): clock-driven provider + Settings Auto/override control

Rewrite useTheme to time-driven {theme,autoTheme,isAuto,setOverride};
replace ThemeToggle with TimeThemeControl; anti-flash inline script."
```

---

### Task 4: Full regression verification

**Files:** none (verification only).

**Interfaces:** consumes the whole feature.

- [ ] **Step 1: Unit tests**

Run: `npm test`
Expected: PASS — existing 104 + new `timeTheme` tests.

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Lint**

Run: `npm run lint`
Expected: no new errors.

- [ ] **Step 4: Build**

Run: `npm run build`
Expected: success.

- [ ] **Step 5: E2E (kill any stray dev server first).**

Run (PowerShell): `Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force; npm run e2e`
Expected: all 6 Playwright specs pass. They do not assert on `data-theme`, so the new theme names don't affect them. If a spec fails on contrast/visibility, read the failure and fix the offending token (do not weaken the selector).

- [ ] **Step 6: Manual smoke (optional, via preview tools).** Start the dev server, open `/settings`, click Auto + each of the 6 period buttons, and confirm: the whole app (chat, operator, landing) retints; the Auto caption shows the current period; reload preserves a pinned override and Auto re-derives from the clock. Confirm `prefers-reduced-motion` disables the crossfade.

- [ ] **Step 7: Final no-op commit guard.** Ensure the tree is clean:

```bash
git status
```
Expected: clean working tree (all changes already committed in Tasks 1–3).

---

## Self-Review

**Spec coverage:**
- §2 time segments → Task 1 (`getThemeForTime`/`msUntilNextTheme`) + tests. ✓
- §3.1 engine → Task 1. ✓
- §3.2 provider (override + auto + reschedule + focus resync + storage migration) → Task 3 Step 1. ✓
- §3.3 anti-flash script → Task 3 Step 5. ✓
- §3.4 neutralize `[data-aira-mode]` accent → Task 2 Step 2. ✓
- §3.5 Settings control (Auto + 6 buttons + caption) → Task 3 Step 2/4. ✓
- §4.1 recipe + §4.2 per-period values + §4.3 pinned status → Task 2 Steps 1–2. ✓
- §5 transitions + gradient v1 swap → Task 2 Steps 3–4. ✓
- §6 regression wall → Task 4. ✓
- §7 files touched → Tasks 1–3 cover every listed file. ✓
- §8 out-of-scope honored (no tailwind colors, no crossfade, no geolocation). ✓
- Carry-forward WCAG sunrise ratios → Task 2 Step 7 + inline sunrise comments. ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete; CSS values explicit. ✓

**Type consistency:** `ThemeName`, `THEME_NAMES`, `THEME_LABELS`, `isThemeName`, `getThemeForTime`, `msUntilNextTheme` used identically in engine, provider, control, and tests. `useTheme()` shape `{theme, autoTheme, isAuto, setOverride}` matches between provider (Task 3 Step 1) and control (Task 3 Step 2). ✓
