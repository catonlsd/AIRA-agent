"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Nav } from "@/components/nav";
import { useAiraMode } from "@/components/mode-provider";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { mode } = useAiraMode();

  const isLandingPage = pathname === "/";
  const isAiraMode = mode === "aira";

  const shellClassName = cn(
    "aira-shell soft-grid min-h-screen text-[var(--text)]",
    isAiraMode ? "aira-research-theme" : "aira-execution-theme"
  );

  if (isLandingPage) {
    return <div className={shellClassName}>{children}</div>;
  }

  return (
    <div className={shellClassName}>
      <div className="flex min-h-screen">
        <Nav />

        <main className="relative min-w-0 flex-1 overflow-x-hidden">
          <div className="pointer-events-none fixed right-10 top-8 z-0 hidden h-28 w-28 rounded-full bg-[var(--accent-glow)] blur-3xl lg:block" />
          <div className="pointer-events-none fixed bottom-10 left-[24rem] z-0 hidden h-36 w-36 rounded-full bg-[var(--secondary-glow)] blur-3xl lg:block" />

          <div className="relative z-10 p-4 sm:p-6 lg:p-8">{children}</div>
        </main>
      </div>
    </div>
  );
}