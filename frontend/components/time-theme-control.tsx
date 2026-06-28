"use client";

import { useEffect, useState } from "react";
import {
  Eye,
  Moon,
  Sun,
  SunMedium,
  Sunrise,
  Sunset,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";
import { THEME_LABELS, THEME_NAMES, type ThemeName } from "@/lib/timeTheme";

const ICONS: Record<ThemeName, LucideIcon> = {
  predawn: Eye,
  sunrise: Sunrise,
  daytime: Sun,
  dusk: SunMedium,
  sunset: Sunset,
  night: Moon,
};

export function TimeThemeControl() {
  const { theme, autoTheme, isAuto, setOverride } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Override is hydrated post-mount; gate active styling to avoid an SSR mismatch.
  useEffect(() => setMounted(true), []);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-1">
        <button
          type="button"
          onClick={() => setOverride(null)}
          aria-pressed={mounted ? isAuto : false}
          className={cn(
            "flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] font-bold transition",
            mounted && isAuto
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
          )}
        >
          Auto
        </button>

        {THEME_NAMES.map((name) => {
          const Icon = ICONS[name];
          const active = mounted && !isAuto && theme === name;

          return (
            <button
              key={name}
              type="button"
              onClick={() => setOverride(name)}
              aria-pressed={active}
              aria-label={`Use ${THEME_LABELS[name]} theme`}
              className={cn(
                "flex items-center gap-1.5 rounded-xl px-2.5 py-2 text-[11px] font-bold transition",
                active
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{THEME_LABELS[name]}</span>
            </button>
          );
        })}
      </div>

      {mounted && isAuto ? (
        <p className="px-1 text-[11px] font-medium text-[var(--text-subtle)]">
          Auto · {THEME_LABELS[autoTheme]} now
        </p>
      ) : null}
    </div>
  );
}
