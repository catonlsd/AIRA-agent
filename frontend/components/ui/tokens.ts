// AIRA-X design-system tokens — the single source of truth for status color,
// spacing rhythm, and the shared structural class strings that were previously
// duplicated inline across the operator console. No visual change: every value here
// is exactly what the components already rendered.

import type { Tone } from "@/lib/operator";
export type { Tone };

/** Unified status color system: tone → utility classes (dot fill / text color). */
export const toneDot: Record<Tone, string> = {
  good: "bg-[var(--success)]",
  warn: "bg-[var(--warning)]",
  bad: "bg-[var(--danger)]",
  muted: "bg-[var(--text-subtle)]",
  info: "bg-[var(--info)]",
  alert: "bg-[var(--alert)]",
};
export const toneText: Record<Tone, string> = {
  good: "text-[var(--success)]",
  warn: "text-[var(--warning)]",
  bad: "text-[var(--danger)]",
  muted: "text-[var(--text-subtle)]",
  info: "text-[var(--info)]",
  alert: "text-[var(--alert)]",
};
/** Back-compat aliases (the names the operator console already uses). */
export const TONE_DOT = toneDot;
export const TONE_TEXT = toneText;

/** Tokenized spacing rhythm — one cadence for the whole dashboard. */
export const SPACE = {
  panel: "p-5",        // panel inner padding
  panelStack: "gap-5", // gap between stacked panels
  header: "mb-3",      // section header → body
  row: "gap-2",        // inline row item gap
  rowPad: "px-2.5 py-1.5",
  tile: "px-3 py-2",
} as const;

/** Shared structural class strings (dedup of the inline literals). */
export const PANEL = "sarvam-card rounded-[1.5rem] p-5";
export const SECTION_LABEL =
  "flex items-center gap-1.5 text-xs font-bold uppercase tracking-[0.16em] text-[var(--text-muted)]";
export const BTN_BASE =
  "inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-11 font-black text-[var(--text-strong)] transition hover:border-[var(--border-strong)] disabled:opacity-50";
/** Back-compat alias used 23× across the operator console. */
export const INC_BTN = BTN_BASE;
