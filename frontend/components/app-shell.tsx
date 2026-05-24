"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Nav } from "@/components/nav";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLandingPage = pathname === "/";

  if (isLandingPage) {
    return (
      <div className="aira-shell soft-grid min-h-screen text-[var(--text)]">
        {children}
      </div>
    );
  }

  return (
    <div className="aira-shell soft-grid min-h-screen text-[var(--text)]">
      <div className="flex min-h-screen">
        <Nav />

        <main className="relative min-w-0 flex-1 overflow-x-hidden">
          <div className="pointer-events-none fixed right-8 top-6 z-0 hidden h-32 w-32 rounded-full bg-[var(--accent-glow)] blur-3xl lg:block" />
          <div className="pointer-events-none fixed bottom-8 left-[24rem] z-0 hidden h-40 w-40 rounded-full bg-[var(--secondary-glow)] blur-3xl lg:block" />

          <div className="relative z-10 p-4 sm:p-6 lg:p-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
