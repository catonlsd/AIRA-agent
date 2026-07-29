# Workspace Layout Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Execute INLINE with a CHECKPOINT after each task — do not start the next task until the user confirms.

**Goal:** Make the workspace the sole owner of decoration and scrolling, clipped and isolated, so no decorative layer can ever touch the sidebar — in every theme and sidebar state — with the sidebar width defined once.

**Architecture:** `main` becomes a non-scrolling, `overflow:hidden; isolation:isolate` workspace containing a pinned absolute decoration layer (AmbientLayer, incl. the side glows) and an inner scroll container that owns page scrolling. Sidebar width comes from two CSS vars; the runtime `ResizeObserver`/`--sidebar-width` offset hack and the viewport-fixed glows are deleted.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind (arbitrary `[var()]`), CSS custom properties.

## Global Constraints

- **Theme-agnostic only.** No `data-theme` conditionals, no Phantom-only or theme-specific layout CSS.
- **No hardcoded offsets / duplicated widths.** Sidebar width lives in `--sidebar-width-expanded` / `--sidebar-width-collapsed` only; no `w-80`/`w-20`/`left-[320px]`/`ml-80`/runtime px publishing.
- **No margin/padding/overflow hacks** to force the seam — the fix is structural (flex + clip + in-workspace decorations).
- **Decorations live inside the workspace**, never the viewport/body/app-root.
- Do **not** modify `lib/timeTheme.ts`, `components/theme-provider.tsx`, `lib/useScrollDepth.ts`, or any test files.
- Regression wall stays green: `npx tsc --noEmit`, `npm run lint` (no new errors), `npm run build`, `npm run e2e` (6 specs), `npm test` (109).
- Run commands from `D:\AIRA-agent\frontend`. Branch `feat/command-theme`.

---

### Task 1: Workspace owns decoration + scrolling

Make `main` the clipped/isolated workspace; move the side glows back inside the
decoration layer (absolute, no offset math); move page scrolling into an inner
container. After this task the glows no longer reference `--sidebar-width`.

**Files:**
- Modify: `frontend/components/app-shell.tsx`
- Modify: `frontend/components/ambient-layer.tsx`
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `AmbientLayer`, `useScrollDepth` (unchanged), `--scroll-depth` on `<html>`.
- Produces: `.layout-workspace` (clip/isolate workspace), `.layout-workspace-scroll` (inner scroller); side glows rendered inside `.ambient-root` as `position:absolute; left:0/right:0`.

- [ ] **Step 1: Re-add the side glows inside the decoration layer** — `frontend/components/ambient-layer.tsx`. Replace the trailing block:

```tsx
      {/* The viewport-fixed side glows live in the shell (outside <main>, which is a
          transformed containing block). The top horizon line stays here — it's
          absolute to the content area, exactly where it belongs. */}
      <div className="scroll-glow-top" aria-hidden="true" />
    </div>
  );
}
```

with (all three glows now live inside the workspace decoration layer):

```tsx
      {/* Scroll glow — global, all themes. Pinned to the workspace box and clipped
          by it; fades in with --scroll-depth. left:0 = workspace's left edge =
          the sidebar's right edge, so no offset math is needed. */}
      <div className="scroll-glow-left" aria-hidden="true" />
      <div className="scroll-glow-right" aria-hidden="true" />
      <div className="scroll-glow-top" aria-hidden="true" />
    </div>
  );
}
```

- [ ] **Step 2: Restructure the shell** — `frontend/components/app-shell.tsx`. Replace the entire two-pane `return (...)` block (the one starting `<div className={cn(shellClassName, "layout-root")}>`) with:

```tsx
  return (
    <div className={cn(shellClassName, "layout-root")}>
      <Nav />

      <main className="layout-workspace min-w-0 flex-1">
        {/* Decoration layer — absolute inset-0, pinned + clipped by the workspace. */}
        <AmbientLayer />

        <div className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-px bg-gradient-to-r from-transparent via-[var(--border-strong)] to-transparent" />

        {/* Scroll container — owns page scrolling; sits above the decoration layer. */}
        <div
          className={cn(
            "layout-workspace-scroll",
            isChat
              ? "flex min-h-0 flex-col overflow-hidden" // chat owns its inner thread scroll
              : "overflow-y-auto p-4 sm:p-6 lg:px-8 lg:py-7"
          )}
        >
          {children}
        </div>
      </main>
    </div>
  );
}
```

This removes: the `layout-main`/`layout-main-fixed` classes on `<main>`, the `fixed right-8 top-6` decorative blob div, and the two shell-level `scroll-glow-left/right` divs (now inside `AmbientLayer`).

- [ ] **Step 3: Add workspace CSS + make glows absolute** — `frontend/app/globals.css`. (a) Replace the `.layout-main, .scroll-region { … }` + `.layout-main-fixed { … }` block:

```css
.layout-main,
.scroll-region {
  height: 100vh;
  height: 100dvh;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
}

/* Chat uses an app-shell scroll model: <main> is viewport-locked and never
   scrolls; the thread container inside the page is the only scroller. */
.layout-main-fixed {
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}
```

with (keep `.scroll-region` for landing/operator; introduce the workspace rules):

```css
.scroll-region {
  height: 100vh;
  height: 100dvh;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
}

/* Workspace: the single owner of decoration + scrolling. A hard clip + isolation
   boundary so no decorative layer (any theme) can paint into the sidebar. It does
   not scroll itself — the inner .layout-workspace-scroll does. Theme-agnostic. */
.layout-workspace {
  height: 100vh;
  height: 100dvh;
  position: relative;
  overflow: hidden;
  isolation: isolate;
}

.layout-workspace-scroll {
  position: relative;
  z-index: 1; /* above the z:0 decoration layer */
  height: 100%;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
```

(b) Change the side-glow position from viewport-fixed to workspace-absolute. Replace:

```css
.scroll-glow-left,
.scroll-glow-right {
  /* Viewport-level: cover the full visible height regardless of content length.
     --scroll-depth still inherits from <html> to drive opacity. */
  position: fixed;
  top: 0;
  bottom: 0;
  width: 80px;
  pointer-events: none;
  opacity: calc(var(--scroll-depth, 0) * 0.75);
  transition: opacity 120ms ease-out; /* smooths out micro-jitter */
  will-change: opacity;
}

.scroll-glow-left {
  /* --sidebar-width is the sidebar's real measured width (published by Nav via a
     ResizeObserver), so the glow stays flush in every state — it even tracks the
     collapse animation live, no CSS left-transition needed. */
  left: var(--sidebar-width, 20rem);
  border-radius: 0 40px 40px 0;
  background: linear-gradient(to right, var(--scroll-glow-color, rgba(255, 255, 255, 0)) 0%, transparent 100%);
}
```

with (absolute inside the workspace decoration layer; `left:0` = sidebar's right edge):

```css
.scroll-glow-left,
.scroll-glow-right {
  /* Pinned to the workspace box (the decoration layer is absolute inset-0 inside
     the non-scrolling workspace) and clipped by it. Full height; opacity from
     --scroll-depth (inherited from <html>). */
  position: absolute;
  top: 0;
  bottom: 0;
  width: 80px;
  pointer-events: none;
  opacity: calc(var(--scroll-depth, 0) * 0.75);
  transition: opacity 120ms ease-out; /* smooths out micro-jitter */
  will-change: opacity;
}

.scroll-glow-left {
  left: 0; /* = workspace left edge = sidebar right edge; no offset math */
  border-radius: 0 40px 40px 0;
  background: linear-gradient(to right, var(--scroll-glow-color, rgba(255, 255, 255, 0)) 0%, transparent 100%);
}
```

- [ ] **Step 4: Typecheck + build** (stop any dev server first so Next's generated types don't race).

Run (PowerShell): `Get-Process node -EA SilentlyContinue | Stop-Process -Force; npx tsc --noEmit`
Expected: no errors.
Run: `npm run build`
Expected: success.

- [ ] **Step 5: Browser verify — no overlap, decorations inside + clipped.** Start preview, set a desktop viewport, force expanded sidebar, scroll, and assert.

```js
// preview_start "frontend"; preview_resize 1440x900; navigate /overview; set localStorage
//   aira-x-theme=phantom, aira-sidebar-collapsed=false; reload; then eval:
(async () => {
  const aside = document.querySelector('aside').getBoundingClientRect();
  const main = document.querySelector('main');
  const left = document.querySelector('.scroll-glow-left');
  const lrect = left.getBoundingClientRect();
  const scroller = main.querySelector('.layout-workspace-scroll');
  scroller.scrollTop = 500; scroller.dispatchEvent(new Event('scroll'));
  await new Promise(r=>setTimeout(r,200));
  return {
    sidebarRight: Math.round(aside.right),
    mainLeft: Math.round(main.getBoundingClientRect().left),
    mainOverlap: Math.round(main.getBoundingClientRect().left) < Math.round(aside.right) - 1,
    glowLeftInsideMain: left.closest('main') !== null,
    glowLeftX: Math.round(lrect.left),
    glowIntrudesSidebar: Math.round(lrect.left) < Math.round(aside.right) - 1,
    workspaceOverflow: getComputedStyle(main).overflow,
    workspaceIsolation: getComputedStyle(main).isolation,
    glowOpacityScrolled: Number(getComputedStyle(left).opacity).toFixed(2),
  };
})()
```
Expected: `mainOverlap:false`, `glowLeftInsideMain:true`, `glowLeftX === sidebarRight`, `glowIntrudesSidebar:false`, `workspaceOverflow:"hidden"`, `workspaceIsolation:"isolate"`, `glowOpacityScrolled > 0`. Also confirm `preview_console_logs` (level error) is empty.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/app-shell.tsx frontend/components/ambient-layer.tsx frontend/app/globals.css
git commit -m "refactor(layout): workspace owns decoration + scrolling (clipped, isolated)"
```

- [ ] **CHECKPOINT 1 — report tsc/build result + the Step 5 measurements; wait for user confirmation before Task 2.**

---

### Task 2: Sidebar width — single source of truth

Replace the `w-80`/`w-20` magic widths and the runtime `ResizeObserver`/`--sidebar-width`
hack with two CSS vars referenced by the sidebar.

**Files:**
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/nav.tsx`

**Interfaces:**
- Consumes: the `collapsed` boolean already in `Nav`.
- Produces: `--sidebar-width-expanded` / `--sidebar-width-collapsed`; the `<aside>` width sourced from them.

- [ ] **Step 1: Define the width vars; remove the dead default** — `frontend/app/globals.css`. Add to the top `:root` token block (right after `color-scheme: dark;` near the top of the file):

```css
  /* Sidebar width — single source of truth (referenced by the aside + its flex). */
  --sidebar-width-expanded: 20rem;
  --sidebar-width-collapsed: 5rem;
```

Then delete the now-unused default block (it fed the deleted glow offset):

```css
:root {
  --sidebar-width: 320px; /* default (expanded w-80 = 20rem); nav updates on collapse */
}
```

- [ ] **Step 2: Source the aside width from the vars** — `frontend/components/nav.tsx`. Replace the `<aside>` opening tag:

```tsx
  return (
    <aside
      ref={asideRef}
      className={cn(
        "relative z-40 flex h-[100dvh] shrink-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] backdrop-blur-2xl transition-[width,padding] duration-300",
        collapsed ? "w-20 px-3 py-5" : "w-80 px-4 py-5"
      )}
    >
```

with (width via the vars; `shrink-0` + explicit width = `flex: 0 0 <width>`; padding kept):

```tsx
  return (
    <aside
      style={{
        width: collapsed
          ? "var(--sidebar-width-collapsed)"
          : "var(--sidebar-width-expanded)",
      }}
      className={cn(
        "relative z-40 flex h-[100dvh] shrink-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] backdrop-blur-2xl transition-[width,padding] duration-300",
        collapsed ? "px-3 py-5" : "px-4 py-5"
      )}
    >
```

- [ ] **Step 3: Delete the ResizeObserver hack + its ref** — `frontend/components/nav.tsx`. Remove this effect entirely:

```tsx
  // Publish the sidebar's REAL rendered width as --sidebar-width so viewport-fixed
  // decorations (e.g. the scroll-glow left edge) sit flush with the rail in any
  // state. A ResizeObserver tracks it across the collapse animation and any
  // font-size/zoom change — no assumptions about rem vs px or fixed widths.
  useEffect(() => {
    const el = asideRef.current;
    if (!el) return;

    const publish = () =>
      document.documentElement.style.setProperty(
        "--sidebar-width",
        `${el.offsetWidth}px`
      );

    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(el);

    return () => observer.disconnect();
  }, []);
```

Remove the now-unused `asideRef` declaration:

```tsx
  const asideRef = useRef<HTMLElement>(null);
```

And drop `useRef` from the React import (keep `useEffect`, `useState`):

```tsx
import { useEffect, useRef, useState } from "react";
```
→
```tsx
import { useEffect, useState } from "react";
```

- [ ] **Step 4: Typecheck + build**

Run (PowerShell): `Get-Process node -EA SilentlyContinue | Stop-Process -Force; npx tsc --noEmit`
Expected: no errors (no remaining `asideRef`/`useRef` references).
Run: `npm run build`
Expected: success.

- [ ] **Step 5: Browser verify — width var drives both states, glow stays flush.** Start preview (1440×900, `/overview`), then:

```js
(async () => {
  const root = document.documentElement;
  const aside = document.querySelector('aside');
  const left = document.querySelector('.scroll-glow-left');
  const snap = (label) => ({ label,
    expVar: getComputedStyle(root).getPropertyValue('--sidebar-width-expanded').trim(),
    colVar: getComputedStyle(root).getPropertyValue('--sidebar-width-collapsed').trim(),
    asideRight: Math.round(aside.getBoundingClientRect().right),
    glowLeft: Math.round(left.getBoundingClientRect().left),
    flush: Math.round(left.getBoundingClientRect().left) === Math.round(aside.getBoundingClientRect().right),
    legacyVar: root.style.getPropertyValue('--sidebar-width') || '(none)',
  });
  const before = snap('initial');
  aside.querySelector('button[aria-label*="idebar"]').click();
  await new Promise(r=>setTimeout(r,600));
  const after = snap('toggled');
  return { before, after };
})()
```
Expected: `expVar:"20rem"`, `colVar:"5rem"`, `flush:true` in both states, `glowLeft === asideRight` in both, `legacyVar:"(none)"` (the runtime hack is gone).

- [ ] **Step 6: Commit**

```bash
git add frontend/app/globals.css frontend/components/nav.tsx
git commit -m "refactor(layout): sidebar width single source of truth (CSS vars)"
```

- [ ] **CHECKPOINT 2 — report tsc/build + Step 5 measurements; wait for confirmation before Task 3.**

---

### Task 3: Full regression + cross-theme / cross-state verification

**Files:** none (verification only).

- [ ] **Step 1: Unit tests** — Run: `npm test` — Expected: **109 pass, 0 fail**.
- [ ] **Step 2: Typecheck** — Run: `npx tsc --noEmit` — Expected: clean.
- [ ] **Step 3: Lint** — Run: `npm run lint` — Expected: 0 errors.
- [ ] **Step 4: Build** — Run: `npm run build` — Expected: success.
- [ ] **Step 5: E2E** — Run (PowerShell): `Get-Process node -EA SilentlyContinue | Stop-Process -Force; npm run e2e` — Expected: **6 passed**.
- [ ] **Step 6: Browser matrix — all 7 themes × both sidebar states.** For each theme in `["predawn","sunrise","daytime","dusk","sunset","night","phantom"]`, set `localStorage["aira-x-theme"]`, reload `/overview`, and assert layout invariants (decorative background may differ, layout must not):

```js
(async () => {
  const themes = ["predawn","sunrise","daytime","dusk","sunset","night","phantom"];
  const out = [];
  for (const t of themes) {
    localStorage.setItem('aira-x-theme', t); location.reload();
    await new Promise(r=>setTimeout(r,1400));
    const aside = document.querySelector('aside').getBoundingClientRect();
    const main = document.querySelector('main').getBoundingClientRect();
    const left = document.querySelector('.scroll-glow-left').getBoundingClientRect();
    out.push({ t,
      mainFlush: Math.round(main.left) === Math.round(aside.right),
      mainOverlap: Math.round(main.left) < Math.round(aside.right) - 1,
      glowAtEdge: Math.round(left.left) === Math.round(aside.right),
    });
    break; // NOTE: reload resets the loop; run one theme per eval call, iterating manually.
  }
  return out;
})()
```
Because `location.reload()` interrupts the loop, run this **once per theme** (set theme + reload, then a second eval to measure). Expected every theme: `mainFlush:true`, `mainOverlap:false`, `glowAtEdge:true`. Also toggle collapse on one light theme + Phantom and re-measure (both flush, no layout shift). Confirm `preview_console_logs` error level empty.

- [ ] **Step 7: Clean tree** — Run: `git status` — Expected: clean (revert any regenerated `frontend/next-env.d.ts`).

- [ ] **CHECKPOINT 3 — report the full matrix; done.**

---

## Self-Review

**Spec coverage:**
- §4.1 sidebar single source → Task 2. ✓
- §4.2 workspace clip/isolate + inner scroll → Task 1 Steps 2–3. ✓
- §4.3 side glows inside decoration layer, absolute, left:0 → Task 1 Steps 1, 3b. ✓
- §4.4 scroll depth unchanged → not modified (listener keys off `closest('main')`; inner scroller is inside main). ✓
- §5 theme independence → no `data-theme` in any task; all rules theme-agnostic. ✓
- §7 acceptance (no overlap, decorations in workspace, single width source, no offsets, all-theme parity, green gates) → Tasks 1–3 + matrix. ✓
- §8 files → app-shell, ambient-layer, globals, nav only. ✓

**Placeholder scan:** No TBD/TODO; all edits show exact before/after code; verification has concrete asserts. ✓

**Type consistency:** Class names used consistently — `.layout-workspace`, `.layout-workspace-scroll`, `.scroll-glow-left/right/top`, `--sidebar-width-expanded/collapsed`. `useScrollDepth` signature untouched. Removal of `asideRef`/`useRef`/`--sidebar-width` is complete across nav + globals (Task 2). ✓
