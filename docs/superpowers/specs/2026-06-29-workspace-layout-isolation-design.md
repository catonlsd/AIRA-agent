# AIRA-X — Workspace Layout Isolation (Design)

**Date:** 2026-06-29
**Branch:** `feat/command-theme`
**Status:** Approved design — proceeding to implementation plan

---

## 1. Problem

The sidebar↔content seam looks unclean (most visible in Phantom because of the
ambient lighting): a crimson glow band sits in the seam and the workspace feels
like it bleeds into / margins against the sidebar. The request: fix this once, in
the shell, theme-agnostically — no Phantom-only or `data-theme` conditionals.

## 2. Root cause (measured: 1440×900, Phantom, expanded sidebar, `/overview`)

**There is no structural overlap.** The shell is already correct flexbox:
- `layout-root`: `display:flex; overflow:hidden`.
- Sidebar: fixed width, `flex-shrink:0`.
- `main`: `flex: 1 1 0%`, left edge **flush at x=320** (sidebar's right edge).
- `mainOverlapsSidebar = false`; no decoration box intrudes into x-range `[0,320]`.

The real defect is **a split decoration layer that is partly attached to the
viewport instead of the workspace**, plus a soft clip boundary:

| Concern | Current state | Verdict |
|---|---|---|
| Ambient blobs (`.ambient-root`) | inside `main`, `position:absolute` | ✅ correct |
| Side scroll-glows | **shell level, `position:fixed`** (viewport), positioned with `left: var(--sidebar-width)` **offset math** | ❌ viewport-attached + fragile offset |
| Workspace clip | `main` is `overflow:hidden auto`, `isolation:auto` | ❌ not a hard clip/isolation boundary; `main` also scrolls |
| Sidebar width | Tailwind `w-80`/`w-20` **and** a runtime `ResizeObserver` publishing `--sidebar-width` | ❌ two sources; the observer exists only to feed the fixed-glow offset |

So the seam looks wrong because a viewport-fixed glow is pushed into the seam by
width math, and the workspace isn't a true clip boundary. The architecture fix
eliminates the whole class of bug.

## 3. Desired architecture

```
Viewport
├── Sidebar          flex: 0 0 var(--sidebar-width); own scroll
└── Workspace (main) flex: 1; position:relative; overflow:hidden; isolation:isolate
      ├── Decoration layer (AmbientLayer)  position:absolute; inset:0; z:0   (pinned, clipped)
      └── Scroll container                 position:relative; z:1; height:100%; overflow-y:auto
            └── page content
```

The workspace owns **all** decoration and **all** scrolling. Decorations are
`absolute; inset:0` inside the workspace, so they're pinned to the workspace box,
clipped by `overflow:hidden`, and **structurally cannot** paint into the sidebar —
no offset math, no `--sidebar-width` reference from decorations.

## 4. Design details

### 4.1 Sidebar — single source of truth
`app/globals.css`:
```css
:root {
  --sidebar-width-expanded: 20rem;  /* was w-80  */
  --sidebar-width-collapsed: 5rem;  /* was w-20  */
}
```
`components/nav.tsx`: the `<aside>` sets its width from the var via the existing
`collapsed` boolean — `style={{ width: collapsed ? "var(--sidebar-width-collapsed)"
: "var(--sidebar-width-expanded)" }}` — and drops the `w-80`/`w-20` classes (keeps
`shrink-0`, padding, the width transition). **Delete** the `ResizeObserver`,
`asideRef`, and the runtime `--sidebar-width` publish (no longer needed once
decorations live in the workspace). The flex basis comes from `shrink-0` + the
explicit width = `flex: 0 0 <width>`.

### 4.2 Workspace — clip + isolate, scrolling moves inward
`app/globals.css`: replace `.layout-main` / `.layout-main-fixed` with one
theme-agnostic rule:
```css
.layout-workspace {
  height: 100vh;
  height: 100dvh;
  position: relative;
  overflow: hidden;        /* hard clip for every decorative layer */
  isolation: isolate;      /* own stacking context */
}
.layout-workspace-scroll {
  position: relative;
  z-index: 1;              /* above the z:0 decoration layer */
  height: 100%;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
```
`components/app-shell.tsx` (two-pane branch):
```tsx
<main className="layout-workspace min-w-0 flex-1">
  <AmbientLayer />
  <div className={cn(
    "layout-workspace-scroll",
    isChat ? "flex min-h-0 flex-col" /* chat owns its inner thread scroll */
           : "overflow-y-auto p-4 sm:p-6 lg:px-8 lg:py-7" /* normal page scroll */
  )}>
    {children}
  </div>
</main>
```
- Non-chat: the scroll container scrolls (`overflow-y:auto`); `main` never scrolls.
- Chat: the scroll container is a non-scrolling flex column; the chat page's own
  thread region keeps its internal scroll + pinned composer (unchanged page code).
- Remove the shell-level fixed side-glow divs and the `fixed right-8 top-6`
  decorative blob (viewport-attached; superseded by the in-workspace decoration
  layer). The top hairline stays (absolute, inside `main`).

### 4.3 Decoration layer — `components/ambient-layer.tsx`
The two side glows move back **inside** `.ambient-root` (which is `absolute;
inset:0` in `main`) alongside the blobs and horizon line. They become
`position:absolute` (not fixed):
```css
.scroll-glow-left  { left: 0;  /* = workspace left = sidebar right edge */ }
.scroll-glow-right { right: 0; }
.scroll-glow-left, .scroll-glow-right { position:absolute; top:0; bottom:0; width:80px; }
```
No `var(--sidebar-width)`. Opacity still `calc(var(--scroll-depth,0) * 0.75)`.
Because `.ambient-root` is in the non-scrolling workspace, the glows are pinned
full-height and clipped — never touching the sidebar, in any theme.

### 4.4 Scroll depth — unchanged
`lib/useScrollDepth.ts` already keys off `el.closest("main") && !el.closest("aside")`.
The inner scroll container is inside `main` → the listener still fires and writes
`--scroll-depth` on `<html>`; the glows (inside the workspace) read it. No change.

## 5. Theme independence

Nothing in this design references `data-theme`. `--scroll-glow-color` and the
period palettes are untouched. The layout engine (`.layout-workspace`,
`.layout-workspace-scroll`, sidebar width vars, decoration positioning) is
identical for all 7 themes and any future theme.

## 6. Out of scope / non-goals
- No change to per-theme palettes, ambient visuals, or the scroll-glow color/opacity feel.
- No change to page content or routes.
- The unexplained identity `transform` on `main` is left alone — with decorations
  now `absolute` (not `fixed`) inside the workspace, it is irrelevant.

## 7. Acceptance criteria (from the request)
- Sidebar never overlaps the workspace; workspace never under the sidebar.
- Decorations remain inside the workspace (clipped; never paint into the sidebar).
- Sidebar width defined once (CSS vars); no duplicated widths / hardcoded offsets.
- Workspace auto-adapts to collapse/expand; no layout shift.
- No theme-specific layout CSS; identical across all 7 themes + both sidebar states.
- Animations stay smooth; `tsc`, `lint`, `build`, Playwright all green.

## 8. Files touched
`app/globals.css` · `components/app-shell.tsx` · `components/ambient-layer.tsx`
· `components/nav.tsx`. (No test files; no `lib/timeTheme.ts`; no `theme-provider.tsx`.)
