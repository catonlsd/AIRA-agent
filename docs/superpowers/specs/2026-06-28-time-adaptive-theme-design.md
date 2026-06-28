# AIRA-X — Time-Adaptive Theme System (Design)

**Date:** 2026-06-28
**Branch:** `feat/command-theme`
**Status:** Approved design — pending spec review → implementation plan

---

## 1. Goal

Replace AIRA-X's manual light/dark/system theme toggle with an **automatic, clock-driven
theme** that cycles through **6 named periods** based on the user's local time, with a
**manual override** surfaced in Settings (Auto + 6 period buttons). Themes apply
**app-wide** (chat, operator console, landing) with smooth crossfades on all surfaces,
text, borders, and shadows.

This is a **frontend-only** change. No backend, route, API, or product-feature changes.
The non-negotiable regression wall (tests, status-color semantics, operator/user
separation) is preserved.

## 2. Time segments

| Theme | Range | Minutes-from-midnight |
|---|---|---|
| `predawn` | 03:00 → 05:29 | 180–329 |
| `sunrise` | 05:30 → 07:59 | 330–479 |
| `daytime` | 08:00 → 16:59 | 480–1019 |
| `dusk` | 17:00 → 18:29 | 1020–1109 |
| `sunset` | 18:30 → 19:14 | 1110–1154 |
| `night` | 19:15 → 02:59 | else (wraps midnight) |

`night` is the fallback (covers 19:15–23:59 and 00:00–02:59 with no special-casing).

## 3. Architecture

### 3.1 Theme engine — `lib/timeTheme.ts` (new, pure, unit-tested)

```ts
export type ThemeName = "predawn" | "sunrise" | "daytime" | "dusk" | "sunset" | "night";
export const THEME_NAMES: readonly ThemeName[];           // ordered list
export const THEME_LABELS: Record<ThemeName, string>;     // "Pre-dawn", "Sunrise", …
export function getThemeForTime(date?: Date): ThemeName;   // minutes-bucket lookup
export function msUntilNextTheme(date?: Date): number;     // ms to next boundary
export function isThemeName(v: unknown): v is ThemeName;   // storage validation
```

Logic is the approved reference implementation (minute buckets; boundary seconds for
`msUntilNextTheme`; wrap to tomorrow's 03:00). No DOM access — fully testable in Node.

### 3.2 Provider — rewrite `components/theme-provider.tsx` (keep path + `useTheme` name)

- State:
  - `override: ThemeName | null` — persisted to `localStorage["aira-x-theme"]`. `null`/absent = Auto.
  - `autoTheme: ThemeName` — from `getThemeForTime()`, refreshed by a self-rescheduling
    `setTimeout(msUntilNextTheme())` and on `visibilitychange`/`focus` (handles a slept laptop).
- Derived: `activeTheme = override ?? autoTheme`.
- Effect: `document.documentElement.dataset.theme = activeTheme`.
- Public API (consumed by the Settings control):
  ```ts
  { theme: ThemeName; autoTheme: ThemeName; isAuto: boolean; setOverride(name: ThemeName | null): void }
  ```
- **Storage migration:** old values (`"light"`/`"dark"`/`"system"`) fail `isThemeName` →
  treated as Auto (override `null`). No crash, no manual migration.

### 3.3 Anti-flash inline script — `app/layout.tsx`

A tiny **blocking** inline `<script>` in `<head>` (runs before first paint) sets
`document.documentElement.dataset.theme` from `localStorage["aira-x-theme"]` if it is a
valid `ThemeName`, else from an inlined copy of the minute-bucket logic. `<html>` keeps
`suppressHydrationWarning`. This eliminates the wrong-theme flash that a pure-`useEffect`
provider would cause. The script is self-contained (no imports).

### 3.4 Mode provider — `components/mode-provider.tsx`

`data-aira-mode="aira-x"` currently overrides `--accent`. **Neutralize that override** (drop
the accent rule from `[data-aira-mode="aira-x"]` in globals.css) so each period owns its own
accent. `mode-provider` otherwise stays as-is.

### 3.5 Settings UI — replace `components/theme-toggle.tsx` → `components/time-theme-control.tsx`

Rendered in the same Settings row (`app/settings/page.tsx`, swap the import). A segmented
control:

- **`Auto`** (first) — active when `isAuto`; click → `setOverride(null)`.
- **6 period buttons** — icon + label, active when `override === name`; click → `setOverride(name)`.
  Icons (lucide): predawn `Moon`, sunrise `Sunrise`, daytime `Sun`, dusk `Sunset`,
  sunset `CloudSun`, night `Stars`.
- When Auto is active, a caption reads `Auto · <current period> now` (uses `autoTheme`).
- Styling reuses the existing toggle's token classes (`--surface-soft`, `--accent`,
  `--accent-foreground`, `--surface-hover`) so it matches the panel.
- This **replaces** the spec's dev-only `ThemeDebugPanel` — the real control covers manual testing.

## 4. Token mapping — the core work (`app/globals.css`)

Components consume AIRA-X's existing **~30-token contract** (`--surface*`, `--text*`,
`--border*`, `--accent*`, `--secondary*`, status, shadows), not the spec's 18 names.
Each period defines **one `[data-theme="<name>"]` block** that maps its palette onto the
full contract via the **uniform recipe** below. `:root` defaults to the `night` palette
(SSR / no-JS / pre-hydration fallback). The dead `[data-theme="dark"]` and
`[data-theme="light"]` blocks are removed.

### 4.1 Uniform recipe (applies to every period)

`color-mix()` is already used in this codebase, so derivations stay concrete and DRY.

| Existing token | Source (from period palette) |
|---|---|
| `--bg` | period **solid** base color (see 4.2) — kept a *color*, not a gradient |
| `--bg-gradient` *(new)* | period `bg-primary` gradient — applied to the page background layer only |
| `--bg-muted` | `bg-tertiary` |
| `--surface` | `bg-secondary` |
| `--surface-soft` | `color-mix(in srgb, var(--surface) 88%, #fff 12%)` |
| `--surface-muted` | `bg-tertiary` |
| `--surface-hover` | `bg-accent` |
| `--surface-strong` | opaque near-`bg-secondary` (per-period solid, see 4.2) |
| `--text-strong` | `text-primary` |
| `--text` | `color-mix(in srgb, var(--text-strong) 82%, var(--text-muted))` |
| `--text-muted` | `text-secondary` |
| `--text-subtle` | `color-mix(in srgb, var(--text-muted) 65%, transparent)` |
| `--border` | `border-default` |
| `--border-strong` | `border-strong` |
| `--accent` | `accent` |
| `--accent-strong` | `accent-hover` |
| `--accent-soft` | `accent-muted` |
| `--accent-foreground` | `text-on-accent` |
| `--accent-glow` | `bg-accent` |
| `--secondary` | `ray-secondary` |
| `--secondary-soft` | `color-mix(in srgb, var(--secondary) 12%, transparent)` |
| `--secondary-glow` | `color-mix(in srgb, var(--secondary) 10%, transparent)` |
| `--shadow-sm` | period `shadow-sm` |
| `--shadow-soft` / `--shadow-card` / `--shadow-panel` | built from period `shadow-md` (white inset hairline dropped on light periods, kept on `night`) |
| `--shadow-hover` / `--shadow-glow` | existing `color-mix(accent …)` formulas — unchanged, auto-retint |
| `--scrollbar-thumb` / `--scrollbar-track` *(new)* | period `scrollbar-thumb` / `scrollbar-track`; wire the scrollbar CSS to them |

### 4.2 Per-period source values

`--bg` solid + `--bg-gradient`; remaining palette values are the approved spec blocks
(backgrounds, text, borders, accent, rays, shadows, scrollbar).

| Period | `--bg` (solid) | `--bg-gradient` |
|---|---|---|
| predawn | `#E2D0F8` | `linear-gradient(160deg, #F5EEFF 0%, #E2D0F8 50%, #D4BFF2 100%)` |
| sunrise | `#FFD54F` | `linear-gradient(160deg, #FFE082 0%, #FFD54F 40%, #FFCA28 100%)` |
| daytime | `#E3F2FD` | `linear-gradient(160deg, #FFFFFF 0%, #E3F2FD 50%, #BBDEFB 100%)` |
| dusk | `#D6E9F8` | `linear-gradient(180deg, #BBDEFB 0%, #E3F2FD 45%, #FFE082 75%, #FFD54F 100%)` |
| sunset | `#F3C8D8` | `linear-gradient(160deg, #E8D5F5 0%, #F3B8D0 40%, #FFB74D 100%)` |
| night | `#2E2C7A` | `#2E2C7A` (solid — no gradient) |

Palette source values per period (mapped via 4.1):

- **predawn** — secondary `bg`: `rgba(240,230,255,0.75)`; tertiary: `rgba(225,210,248,0.6)`;
  bg-accent: `rgba(139,92,246,0.12)`; text-primary `#3B1F6B`; text-secondary `#6B4FA0`;
  on-accent `#ffffff`; border-default `rgba(139,92,246,0.18)`; border-strong
  `rgba(139,92,246,0.45)`; accent `#7C3AED`; accent-hover `#6D28D9`; accent-muted
  `rgba(124,58,237,0.10)`; ray-secondary `#4040C0`; shadow-sm `0 1px 3px rgba(100,60,200,0.10)`;
  shadow-md `0 4px 16px rgba(100,60,200,0.15)`; scrollbar-thumb `#C4A8F0`; track `#EDE5FF`;
  surface-strong `#F0E8FF`.
- **sunrise** — secondary `rgba(255,235,180,0.80)`; tertiary `rgba(255,220,150,0.65)`;
  bg-accent `rgba(233,30,140,0.10)`; text-primary `#6B1A3A`; text-secondary `#9C2865`;
  border-default `rgba(233,30,140,0.18)`; border-strong `rgba(233,30,140,0.45)`; accent
  `#E91E8C`; accent-hover `#C2185B`; accent-muted `rgba(233,30,140,0.10)`; ray-secondary
  `#6B21A8`; shadow-sm `0 1px 3px rgba(180,80,20,0.12)`; shadow-md `0 4px 16px rgba(180,80,20,0.18)`;
  scrollbar-thumb `#F48FB1`; track `#FFF9C4`; surface-strong `#FFF3D6`.
- **daytime** — secondary `rgba(255,255,255,0.90)`; tertiary `rgba(232,244,253,0.70)`;
  bg-accent `rgba(21,101,192,0.08)`; text-primary `#0D2B5E`; text-secondary `#1565C0`;
  border-default `rgba(21,101,192,0.15)`; border-strong `rgba(21,101,192,0.40)`; accent
  `#1976D2`; accent-hover `#1565C0`; accent-muted `rgba(25,118,210,0.08)`; ray-secondary
  `#42A5F5`; shadow-sm `0 1px 3px rgba(21,101,192,0.10)`; shadow-md `0 4px 16px rgba(21,101,192,0.14)`;
  scrollbar-thumb `#90CAF9`; track `#E3F2FD`; surface-strong `#FFFFFF`.
- **dusk** — secondary `rgba(230,245,255,0.82)`; tertiary `rgba(210,235,255,0.65)`;
  bg-accent `rgba(255,160,0,0.10)`; text-primary `#1A3050`; text-secondary `#2E5FA3`;
  border-default `rgba(21,101,192,0.15)`; border-strong `rgba(255,160,0,0.45)`; accent
  `#0288D1`; accent-hover `#0277BD`; accent-muted `rgba(2,136,209,0.10)`; ray-secondary
  `#FFA000`; shadow-sm `0 1px 3px rgba(21,101,192,0.10)`; shadow-md `0 4px 16px rgba(21,101,192,0.15)`;
  scrollbar-thumb `#90CAF9`; track `#E3F2FD`; surface-strong `#EAF4FF`.
- **sunset** — secondary `rgba(245,225,248,0.80)`; tertiary `rgba(235,208,242,0.65)`;
  bg-accent `rgba(224,64,251,0.10)`; text-primary `#4A1560`; text-secondary `#9C27B0`;
  border-default `rgba(224,64,251,0.18)`; border-strong `rgba(224,64,251,0.42)`; accent
  `#AB47BC`; accent-hover `#8E24AA`; accent-muted `rgba(171,71,188,0.10)`; ray-secondary
  `#FF7043`; shadow-sm `0 1px 3px rgba(150,40,180,0.10)`; shadow-md `0 4px 16px rgba(150,40,180,0.18)`;
  scrollbar-thumb `#CE93D8`; track `#F3E5F5`; surface-strong `#F7E9FA`.
- **night** — secondary `rgba(50,48,110,0.90)`; tertiary `rgba(60,58,130,0.75)`;
  bg-accent `rgba(255,255,255,0.06)`; text-primary `#E8E6FF`; text-secondary `#A89FCC`;
  on-accent `#1A1850`; border-default `rgba(255,255,255,0.10)`; border-strong
  `rgba(255,255,255,0.28)`; accent `#9FA8DA`; accent-hover `#C5CAE9`; accent-muted
  `rgba(159,168,218,0.12)`; ray-secondary `#B0A8FF`; shadow-sm `0 1px 3px rgba(0,0,0,0.35)`;
  shadow-md `0 4px 16px rgba(0,0,0,0.45)`; scrollbar-thumb `#5C5A8E`; track `#252360`;
  surface-strong `#323070`.

### 4.3 Status colors (pinned — regression-wall guarantee)

Held constant per background family; **never** derived from accent. `*-soft` =
`color-mix(in srgb, <token> 12%, transparent)`.

| Token | Light-bg periods (predawn, sunrise, daytime, dusk, sunset) | `night` |
|---|---|---|
| `--success` | `#047857` | `#34d399` |
| `--warning` | `#b45309` | `#fbbf24` |
| `--danger` | `#b91c1c` | `#f87171` |
| `--info` | `#0369a1` | `#60a5fa` |
| `--alert` | `#c2410c` | `#fb923c` |

## 5. Smooth transition + gradient handling

Added to `globals.css`:

```css
*, *::before, *::after {
  transition:
    background-color 800ms cubic-bezier(0.4,0,0.2,1),
    border-color 800ms cubic-bezier(0.4,0,0.2,1),
    color 800ms cubic-bezier(0.4,0,0.2,1),
    box-shadow 800ms ease;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; }
}
```

- The page gradient lives on a fixed full-viewport background layer
  (`body::before { background: var(--bg-gradient); }`, `position: fixed; inset: 0; z-index: -1`).
- **Gradient = v1 swap only (decided).** CSS can't interpolate a `linear-gradient` swap, so
  the page background changes instantly at a boundary while every surface/text/border/shadow
  crossfades (800ms). Acceptable: ≤6 transitions/day, at boundaries. No 2-layer crossfade in v1.
- Existing flat-dark body rules (`body::before { display:none }`, vignette removal) are
  replaced by this gradient layer.

## 6. Regression wall (must stay green)

- `npx tsc --noEmit` — clean.
- `npm run lint` — no new errors (existing pre-existing warnings unchanged).
- `npm run build` — succeeds.
- `npm run e2e` — 6 Playwright specs (kill stray `next dev` first). They don't assert on
  `data-theme` values → unaffected.
- `node --test "lib/**/*.test.mts"` — existing 104 **+ new `lib/timeTheme.test.mts`**
  (boundary minutes 02:59/03:00, 05:29/05:30, 07:59/08:00, 16:59/17:00, 18:29/18:30,
  19:14/19:15; `msUntilNextTheme` at sample clocks; `isThemeName` accept/reject incl. legacy
  `"dark"`).
- Backend suite untouched (no backend changes).
- Guarantees preserved: status colors semantic & decoupled from accent; operator/user
  separation unchanged; no API/route/feature changes; protected e2e selectors unchanged.

## 7. Files touched

| File | Change |
|---|---|
| `lib/timeTheme.ts` | **new** — engine |
| `lib/timeTheme.test.mts` | **new** — unit tests |
| `components/theme-provider.tsx` | **rewrite** — time-driven + override, same `useTheme` name |
| `components/time-theme-control.tsx` | **new** — replaces `theme-toggle.tsx` |
| `components/theme-toggle.tsx` | **delete** |
| `app/settings/page.tsx` | swap `ThemeToggle` → `TimeThemeControl` import/usage |
| `app/layout.tsx` | anti-flash inline script; drop `themeColor:"#212121"` static (now period-driven via JS meta update) |
| `app/globals.css` | 6 `[data-theme]` period blocks; `:root` = night; remove dead dark/light blocks; gradient layer; transition rules; neutralize `[data-aira-mode]` accent; wire scrollbar tokens |
| `components/mode-provider.tsx` | no code change required (accent override removed in CSS) |

## 8. Out of scope (YAGNI)

- 2-layer gradient crossfade (deferred — v1 is swap).
- `tailwind.config.ts` token-color additions (components use arbitrary `[var()]`, not Tailwind color utilities — dead weight).
- Geolocation / sunrise-API real solar times (uses local clock buckets only).
- Per-route theming, user-defined custom palettes, persistence of Auto vs override beyond localStorage.
- Backend, API, routes, product features.

## 9. Risks / notes

- **Vivid light periods are a deliberate departure** from the recently-landed flat neutral
  dark look. This is the explicit feature intent. Manual override + Auto give the escape hatch.
- Dense operator tables on bright gradients: contrast is handled by the surface ladder
  (frosted `--surface*`) + pinned dark status colors; verify visually during implementation.
- `themeColor` `<meta>` becomes dynamic (updated by the provider per active period) so the
  mobile browser chrome matches.
