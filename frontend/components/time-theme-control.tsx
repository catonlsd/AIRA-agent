"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";
import { THEME_LABELS, THEME_NAMES } from "@/lib/timeTheme";

export function TimeThemeControl() {
  const { theme, autoTheme, isAuto, setOverride } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Override is hydrated post-mount; gate active styling to avoid an SSR mismatch.
  useEffect(() => setMounted(true), []);

  // Phantom is a manual-only override (never part of the clock rotation).
  const phantomActive = mounted && !isAuto && theme === "phantom";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-1">
        <button
          type="button"
          onClick={() => setOverride(null)}
          aria-pressed={mounted ? isAuto : false}
          className={cn(
            "flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] font-bold transition duration-fast active:scale-[0.985]",
            mounted && isAuto
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
          )}
        >
          Auto
        </button>

        {THEME_NAMES.map((name) => {
          const active = mounted && !isAuto && theme === name;

          return (
            <button
              key={name}
              type="button"
              onClick={() => setOverride(name)}
              aria-pressed={active}
              aria-label={`Use ${THEME_LABELS[name]} theme`}
              className={cn(
                "flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-[11px] font-bold transition duration-fast active:scale-[0.985]",
                active
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
              )}
            >
              <span>{THEME_LABELS[name]}</span>
            </button>
          );
        })}

        {/* Phantom — manual-only, divided from the clock periods */}
        <div className="ml-1 flex border-l border-[var(--border)] pl-1">
          <button
            type="button"
            onClick={() => setOverride("phantom")}
            aria-pressed={phantomActive}
            aria-label="Use Phantom theme"
            className={cn(
              "flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-[11px] font-bold transition duration-fast active:scale-[0.985]",
              phantomActive
                ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
            )}
          >
            <span>{THEME_LABELS.phantom}</span>
          </button>
        </div>
      </div>

      {mounted && phantomActive ? (
        <p className="px-1 text-[11px] font-medium text-[var(--text-subtle)]">
          Phantom · Manual
        </p>
      ) : mounted && isAuto ? (
        <p className="px-1 text-[11px] font-medium text-[var(--text-subtle)]">
          Auto · {THEME_LABELS[autoTheme]} now
        </p>
      ) : null}
    </div>
  );
}
