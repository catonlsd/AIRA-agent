"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";

const themeOptions = [
  {
    value: "system" as const,
    label: "System",
    icon: Monitor,
  },
  {
    value: "light" as const,
    label: "Light",
    icon: Sun,
  },
  {
    value: "dark" as const,
    label: "Dark",
    icon: Moon,
  },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-1">
      <div className="grid grid-cols-3 gap-1">
        {themeOptions.map((option) => {
          const Icon = option.icon;
          const active = theme === option.value;

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setTheme(option.value)}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-xl px-2.5 py-2 text-[11px] font-bold transition",
                active
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
              )}
              aria-label={`Use ${option.label} theme`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}