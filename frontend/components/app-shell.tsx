"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Nav } from "@/components/nav";
import { AmbientLayer } from "@/components/ambient-layer";
import { useScrollDepth } from "@/lib/useScrollDepth";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  // Drives --scroll-glow opacity from the main content scroll position. Global
  // (one capture listener); keyed on pathname so a new route starts at rest.
  useScrollDepth(300, pathname);

  const isLandingPage = pathname === "/";
  // The operator console is OPERATOR-ONLY and renders without the product nav, so
  // it stays clearly separate from the normal user product (never linked in Nav).
  const isOperator = pathname === "/operator" || pathname.startsWith("/operator/");
  // Chat owns its scroll internally (thread scrolls, composer pinned), so <main>
  // is viewport-locked instead of being the page scroller.
  const isChat = pathname === "/chat" || pathname.startsWith("/chat/");

  const shellClassName = cn(
    "aira-shell aira-production-theme soft-grid text-[var(--text)]"
  );

  // Landing + operator render without the product nav. They are their own single
  // scroll viewport (body is locked; the scroll region lives here, not on <body>).
  if (isLandingPage || isOperator) {
    return <div className={cn(shellClassName, "scroll-region")}>{children}</div>;
  }

  // Two-pane app shell: the sidebar and main content are INDEPENDENT scroll viewports.
  // `layout-root` is a flex column-locked-to-100dvh; `<Nav>` owns its scroll, `<main>`
  // (layout-main) owns the page scroll. The body never scrolls.
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