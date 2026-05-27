"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Nav } from "@/components/nav";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const isLandingPage = pathname === "/";

  const shellClassName = cn(
    "aira-shell aira-production-theme soft-grid min-h-screen text-[var(--text)]"
  );

  if (isLandingPage) {
    return <div className={shellClassName}>{children}</div>;
  }

  return (
    <div className={shellClassName}>
      <div className="flex min-h-screen">
        <Nav />

        <main className="relative min-w-0 flex-1 overflow-x-hidden">
          <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-px bg-gradient-to-r from-transparent via-[var(--border-strong)] to-transparent" />
          <div className="pointer-events-none fixed right-8 top-6 z-0 hidden h-40 w-40 rounded-full bg-[var(--accent-glow)] opacity-70 blur-3xl lg:block" />

          <div className="relative z-10 p-4 sm:p-6 lg:px-8 lg:py-7">{children}</div>
        </main>
      </div>
    </div>
  );
}