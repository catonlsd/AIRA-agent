"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type TechnicalDetailsPanelProps = {
  children: ReactNode;
  className?: string;
  summary?: string;
};

export function TechnicalDetailsPanel({
  children,
  className,
  summary = "Technical details",
}: TechnicalDetailsPanelProps) {
  return (
    <details
      className={cn(
        "rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4",
        className
      )}
    >
      <summary className="cursor-pointer select-none text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
        {summary}
      </summary>

      <div className="mt-4 space-y-3">{children}</div>
    </details>
  );
}

export function TechnicalDetailsGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{children}</div>;
}

export function TechnicalDetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <p className="text-[10px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 break-words text-sm font-semibold text-[var(--text-strong)]",
          mono && "font-mono text-xs"
        )}
      >
        {value}
      </p>
    </div>
  );
}
