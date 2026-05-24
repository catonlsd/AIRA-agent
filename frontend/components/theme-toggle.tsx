"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";

const themeOptions = [
  {
    value: "system" as const,
    label: "System",
    shortLabel: "Auto",
    icon: Monitor,
  },
  {
    value: "light" as const,
    label: "Light",
    shortLabel: "Light",
    icon: Sun,
  },
  {
    value: "dark" as const,
    label: "Dark",
    shortLabel: "Dark",
    icon: Moon,
  },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-1 shadow-[var(--shadow-soft)] backdrop-blur-xl">
      <div className="grid grid-cols-3 gap-1">
        {themeOptions.map((option) => {
          const Icon = option.icon;
          const active = theme === option.value;

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setTheme(option.value)}
              aria-label={`Use ${option.label} theme`}
              aria-pressed={active}
              className={cn(
                "group relative flex items-center justify-center gap-1.5 overflow-hidden rounded-xl px-2.5 py-2 text-[11px] font-black transition-all duration-200",
                active
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              )}
            >
              {active && (
                <span className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.18),transparent_42%,rgba(255,255,255,0.08))]" />
              )}

              <Icon
                className={cn(
                  "relative z-10 h-3.5 w-3.5 transition-transform duration-200",
                  active
                    ? "scale-110"
                    : "group-hover:-translate-y-0.5 group-hover:scale-110"
                )}
              />

              <span className="relative z-10 hidden sm:inline">
                {option.label}
              </span>

              <span className="relative z-10 sm:hidden">
                {option.shortLabel}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}