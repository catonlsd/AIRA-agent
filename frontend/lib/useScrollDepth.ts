"use client";

import { useEffect } from "react";

/**
 * Drives the global `--scroll-depth` CSS variable (0.0 → 1.0) on <html> from the
 * main content area's scroll position. The scroll-glow elements read it.
 *
 * AIRA-X has two scroll models: on /chat the inner thread div scrolls (main is
 * locked); on other routes <main> itself scrolls. Rather than wire refs per page,
 * this attaches ONE capture-phase listener on the document and reacts to whichever
 * element inside <main> (never the sidebar) scrolls. requestAnimationFrame-throttled.
 *
 * @param maxDepth  Scroll distance (px) at which depth reaches 1.0.
 * @param resetKey  Changing this (e.g. the pathname) resets depth to 0 — so a fresh
 *                  route starts at rest instead of inheriting the previous scroll.
 */
export function useScrollDepth(maxDepth = 300, resetKey?: string) {
  useEffect(() => {
    const root = document.documentElement;
    let rafId: number | null = null;
    let pending: HTMLElement | null = null;

    // Fresh route / mount starts at rest.
    root.style.setProperty("--scroll-depth", "0");

    const apply = () => {
      rafId = null;
      if (!pending) return;
      const depth = Math.min(Math.max(pending.scrollTop, 0) / maxDepth, 1);
      root.style.setProperty("--scroll-depth", depth.toFixed(3));
    };

    const onScroll = (event: Event) => {
      const el = event.target as HTMLElement | null;
      // Only the main content scroller — not the sidebar, not non-element targets.
      if (!el || typeof el.scrollTop !== "number" || !el.closest) return;
      if (!el.closest("main") || el.closest("aside")) return;
      pending = el;
      if (rafId === null) rafId = requestAnimationFrame(apply);
    };

    document.addEventListener("scroll", onScroll, { capture: true, passive: true });

    return () => {
      document.removeEventListener("scroll", onScroll, { capture: true });
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [maxDepth, resetKey]);
}
