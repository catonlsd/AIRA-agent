"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BookOpen,
  ChevronRight,
  Database,
  GitBranch,
  History,
  LayoutDashboard,
  MessageSquare,
  Palette,
  Settings2,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAiraMode, type AiraOperatingMode } from "@/components/mode-provider";

type NavItem = {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  badge?: string;
};

const airaLinks: NavItem[] = [
  {
    href: "/chat",
    label: "Ask AIRA",
    description: "Research, upload docs, and get grounded answers",
    icon: MessageSquare,
    badge: "Research",
  },
  {
    href: "/documents",
    label: "Knowledge Base",
    description: "Uploaded documents and sources",
    icon: Database,
  },
  {
    href: "/history",
    label: "Interactions",
    description: "Conversation and research history",
    icon: History,
  },
  {
    href: "/settings",
    label: "Appearance",
    description: "Theme and interface settings",
    icon: Palette,
  },
];

const airaXLinks: NavItem[] = [
  {
    href: "/overview",
    label: "Command Center",
    description: "Platform health and execution state",
    icon: LayoutDashboard,
  },
  {
    href: "/chat",
    label: "Execute",
    description: "Launch research and execution tasks",
    icon: TerminalSquare,
    badge: "Core",
  },
  {
    href: "/workflows",
    label: "Workflows",
    description: "Runs, traces, logs, and outcomes",
    icon: GitBranch,
  },
  {
    href: "/approvals",
    label: "Approvals",
    description: "Human-gated actions and safety checks",
    icon: ShieldCheck,
    badge: "Safe",
  },
  {
    href: "/settings",
    label: "System Console",
    description: "Appearance, agents, tools, and policies",
    icon: Settings2,
  },
];

function isActivePath(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}

function getModeHome(mode: AiraOperatingMode) {
  return mode === "aira" ? "/chat" : "/overview";
}

function getModeTitle(mode: AiraOperatingMode) {
  return mode === "aira" ? "AIRA" : "AIRA-X";
}

function getModeSubtitle(mode: AiraOperatingMode) {
  return mode === "aira" ? "Research Assistant" : "Execution Command Center";
}

function getModeDescription(mode: AiraOperatingMode) {
  return mode === "aira"
    ? "Grounded research, document intake, citations, and knowledge retrieval."
    : "Plan, execute, approve, validate, and trace autonomous workflows.";
}

function ModeSwitcher() {
  const router = useRouter();
  const { mode, setMode } = useAiraMode();

  function handleModeChange(nextMode: AiraOperatingMode) {
    setMode(nextMode);
    router.push(getModeHome(nextMode));
  }

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-1">
      <div className="grid grid-cols-2 gap-1">
        <button
          type="button"
          onClick={() => handleModeChange("aira")}
          className={cn(
            "flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-black transition",
            mode === "aira"
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          )}
        >
          <BookOpen className="h-3.5 w-3.5" />
          AIRA
        </button>

        <button
          type="button"
          onClick={() => handleModeChange("aira-x")}
          className={cn(
            "flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-black transition",
            mode === "aira-x"
              ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          )}
        >
          <Zap className="h-3.5 w-3.5" />
          AIRA-X
        </button>
      </div>
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex items-center gap-3 rounded-2xl border px-3 py-3 transition-all duration-200",
        "hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:shadow-[var(--shadow-soft)]",
        active
          ? "border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--text-strong)] shadow-[var(--shadow-soft)]"
          : "border-transparent text-[var(--text-muted)]"
      )}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-7 w-1 -translate-y-1/2 rounded-r-full bg-[var(--accent)] shadow-[0_0_18px_var(--accent-glow)]" />
      )}

      <div
        className={cn(
          "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border transition-all duration-200",
          active
            ? "border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--accent)]"
            : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-subtle)] group-hover:border-[var(--border-strong)] group-hover:text-[var(--accent)]"
        )}
      >
        <Icon className="h-4 w-4 transition-transform duration-200 group-hover:scale-110" />

        {active && (
          <span className="absolute inset-0 rounded-2xl shadow-[0_0_24px_var(--accent-glow)]" />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={cn(
              "truncate text-sm font-bold leading-none",
              active ? "text-[var(--text-strong)]" : "text-[var(--text)]"
            )}
          >
            {item.label}
          </p>

          {item.badge && (
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wide",
                active
                  ? "border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--border)] bg-[var(--secondary-soft)] text-[var(--secondary)]"
              )}
            >
              {item.badge}
            </span>
          )}
        </div>

        <p className="mt-1 truncate text-[11px] font-medium text-[var(--text-subtle)] group-hover:text-[var(--text-muted)]">
          {item.description}
        </p>
      </div>

      <ChevronRight
        className={cn(
          "h-4 w-4 shrink-0 transition-all duration-200",
          active
            ? "translate-x-0 text-[var(--accent)] opacity-100"
            : "-translate-x-1 text-[var(--text-subtle)] opacity-0 group-hover:translate-x-0 group-hover:opacity-100"
        )}
      />
    </Link>
  );
}

export function Nav() {
  const pathname = usePathname();
  const { mode } = useAiraMode();

  const links = useMemo(
    () => (mode === "aira" ? airaLinks : airaXLinks),
    [mode]
  );

  return (
    <aside className="sticky top-0 z-40 flex h-screen w-80 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] px-4 py-5 shadow-[var(--shadow-card)] backdrop-blur-2xl">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-24 top-0 h-48 w-48 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="absolute -bottom-24 right-0 h-56 w-56 rounded-full bg-[var(--secondary-glow)] blur-3xl" />
        <div className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-[var(--border-strong)] to-transparent" />
      </div>

      <Link
        href={getModeHome(mode)}
        className="group mb-4 block rounded-[1.75rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4 shadow-[var(--shadow-soft)] transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
      >
        <div className="flex items-center gap-3">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--accent)] shadow-[0_0_30px_var(--accent-glow)] transition-transform duration-200 group-hover:rotate-2 group-hover:scale-105">
            {mode === "aira" ? (
              <BookOpen className="h-5 w-5" />
            ) : (
              <Sparkles className="h-5 w-5" />
            )}
            <span className="absolute inset-0 rounded-2xl bg-[var(--accent-soft)] blur-xl" />
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-xl font-black tracking-tight text-[var(--text-strong)]">
                {getModeTitle(mode)}
              </h1>

              <span className="rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.18em] text-[var(--accent)]">
                {mode === "aira" ? "Research" : "Ops"}
              </span>
            </div>

            <p className="mt-1 text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">
              {getModeSubtitle(mode)}
            </p>
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-[var(--text-subtle)]">
              Operating Mode
            </span>

            {mode === "aira" ? (
              <BookOpen className="h-3.5 w-3.5 text-[var(--accent)]" />
            ) : (
              <Zap className="h-3.5 w-3.5 text-[var(--accent)]" />
            )}
          </div>

          <p className="text-xs leading-5 text-[var(--text-muted)]">
            {getModeDescription(mode)}
          </p>
        </div>
      </Link>

      <div className="mb-5">
        <ModeSwitcher />
      </div>

      <div className="mb-3 flex items-center justify-between px-2">
        <p className="text-[11px] font-black uppercase tracking-[0.22em] text-[var(--text-subtle)]">
          {mode === "aira" ? "Research Mode" : "Mission Control"}
        </p>

        {mode === "aira" ? (
          <BookOpen className="h-3.5 w-3.5 text-[var(--accent)] opacity-80" />
        ) : (
          <Activity className="h-3.5 w-3.5 text-[var(--accent)] opacity-80" />
        )}
      </div>

      <nav className="space-y-1.5">
        {links.map((item) => (
          <NavLink
            key={`${mode}-${item.href}-${item.label}`}
            item={item}
            active={isActivePath(pathname, item.href)}
          />
        ))}
      </nav>
    </aside>
  );
}
