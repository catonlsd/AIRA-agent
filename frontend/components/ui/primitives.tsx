// AIRA-X shared UI primitives. Each encapsulates the EXACT class strings the operator
// console already rendered, so adopting them is a pure refactor (no visual change).
// These are the stable foundation Slice 4 (observability) is built on.

import { type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { toneDot, toneText, BTN_BASE, PANEL, SECTION_LABEL, type Tone } from "./tokens";

/** Pill button (the former INC_BTN). Forwards all native button props. */
export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn(BTN_BASE, className)} {...props} />;
}

/** Tone-colored status pill with a leading dot. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-0.5 text-[11px] font-black uppercase tracking-wide", toneText[tone])}>
      <span className={cn("h-1.5 w-1.5 rounded-full", toneDot[tone])} aria-hidden="true" />
      {children}
    </span>
  );
}
/** Semantic alias for status contexts (identical visual). */
export const StatusPill = Badge;

/** Big value over a caption (e.g. Overview counters). */
export function StatTile({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2">
      <p className="text-lg font-black text-[var(--text-strong)]">{value}</p>
      <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-subtle)]">{label}</p>
    </div>
  );
}
/** Back-compat name (operator overview imports `Stat`). */
export const Stat = StatTile;

/** Caption over a tonal value (e.g. SLO tiles in the observability panel). */
export function MetricTile({ label, value, tone = "muted" }: { label: string; value: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-[var(--text-subtle)]">{label}</p>
      <p className={cn("text-lg font-black", toneText[tone])}>{value}</p>
    </div>
  );
}

/** Base glass card — matches the existing `.sarvam-card` section. */
export function Card({ className, children, ...props }: HTMLAttributes<HTMLElement> & { children: ReactNode }) {
  return (
    <section className={cn(PANEL, className)} {...props}>
      {children}
    </section>
  );
}

/** Tracked uppercase section header: icon + title + optional sub + trailing actions. */
export function SectionHeader({ icon, title, sub, children, className }: {
  icon?: ReactNode; title: ReactNode; sub?: ReactNode; children?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-baseline gap-2", className)}>
      <p className={SECTION_LABEL}>{icon}{title}</p>
      {sub ? <span className="text-[11px] text-[var(--text-muted)]">{sub}</span> : null}
      {children}
    </div>
  );
}

/** Card + SectionHeader — the standard dashboard panel. */
export function Panel({ icon, title, sub, actions, className, children }: {
  icon?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode; className?: string; children: ReactNode;
}) {
  return (
    <Card className={className}>
      <SectionHeader icon={icon} title={title} sub={sub}>{actions}</SectionHeader>
      {children}
    </Card>
  );
}

/** Pill tab strip (generic; for future adoption + Slice 4 sub-navigation). */
export function Tabs<T extends string>({ tabs, active, onChange, className }: {
  tabs: { id: T; label: ReactNode; icon?: ReactNode }[]; active: T; onChange: (id: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={cn("flex flex-wrap gap-1", className)}>
      {tabs.map((t) => (
        <button
          key={t.id} type="button" role="tab" aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold transition",
            active === t.id
              ? "bg-[var(--accent-soft)] text-[var(--accent)]"
              : "text-[var(--text-muted)] hover:text-[var(--text-strong)]",
          )}
        >
          {t.icon}{t.label}
        </button>
      ))}
    </div>
  );
}
