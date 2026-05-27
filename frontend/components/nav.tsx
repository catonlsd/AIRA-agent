"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  Activity,
  ChevronRight,
  Database,
  GitBranch,
  History,
  LayoutDashboard,
  Settings2,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  badge?: string;
  aliases?: string[];
};

const SIDEBAR_STORAGE_KEY = "aira-sidebar-collapsed";

const navLinks: NavItem[] = [
  {
    href: "/chat",
    label: "Assistant",
    description: "Chat, research, execution, and follow-ups",
    icon: Sparkles,
  },
  {
    href: "/overview",
    label: "Operations",
    description: "Health, throughput, and workflow metrics",
    icon: LayoutDashboard,
  },
  {
    href: "/workflows",
    label: "Workflows",
    description: "Run history, traces, and outcomes",
    icon: GitBranch,
  },
  {
    href: "/approvals",
    label: "Approvals",
    description: "Review and resolve gated actions",
    icon: ShieldCheck,
  },
  {
    href: "/documents",
    label: "Knowledge",
    description: "Indexed documents and retrieval sources",
    icon: Database,
  },
  {
    href: "/history",
    label: "History",
    description: "Stored conversation turns and context",
    icon: History,
    aliases: ["/upload"],
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Runtime, policies, agents, and tools",
    icon: Settings2,
    aliases: ["/agents", "/tools"],
  },
];

function isActivePath(pathname: string, item: NavItem) {
  const paths = [item.href, ...(item.aliases || [])];

  return paths.some((href) => {
    if (href === "/") {
      return pathname === "/";
    }

    return pathname === href || pathname.startsWith(`${href}/`);
  });
}

function getStoredSidebarCollapsed() {
  if (typeof window === "undefined") {
    return false;
  }

  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
}

function NavLink({
  item,
  active,
  collapsed,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
}) {
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      title={collapsed ? `${item.label} — ${item.description}` : undefined}
      className={cn(
        "group relative flex items-center rounded-2xl border transition-all duration-200",
        collapsed
          ? "h-12 justify-center px-0 py-0"
          : "gap-3 px-3 py-3 hover:-translate-y-0.5",
        "hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:shadow-[var(--shadow-soft)]",
        active
          ? "border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--text-strong)] shadow-[var(--shadow-soft)]"
          : "border-transparent text-[var(--text-muted)]"
      )}
    >
      {active && (
        <span
          className={cn(
            "absolute bg-[var(--accent)] shadow-[0_0_18px_var(--accent-glow)]",
            collapsed
              ? "left-1 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full"
              : "left-0 top-1/2 h-7 w-1 -translate-y-1/2 rounded-r-full"
          )}
        />
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

      {!collapsed && (
        <>
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
        </>
      )}
    </Link>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(getStoredSidebarCollapsed());
  }, []);

  function toggleSidebar() {
    setCollapsed((currentValue) => {
      const nextValue = !currentValue;

      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(nextValue));

      return nextValue;
    });
  }

  return (
    <aside
      className={cn(
        "sticky top-0 z-40 flex h-screen shrink-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] backdrop-blur-2xl transition-[width,padding] duration-300",
        collapsed ? "w-20 px-3 py-5" : "w-80 px-4 py-5"
      )}
    >
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-24 top-0 h-48 w-48 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="absolute -bottom-24 right-0 h-56 w-56 rounded-full bg-[var(--secondary-glow)] blur-3xl" />
        <div className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-[var(--border-strong)] to-transparent" />
      </div>

      <div
        className={cn(
          "mb-3 flex",
          collapsed ? "justify-center" : "justify-end"
        )}
      >
        <button
          type="button"
          onClick={toggleSidebar}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)] shadow-[var(--shadow-soft)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--accent)]"
        >
          <ChevronRight
            className={cn(
              "h-4 w-4 transition-transform duration-300",
              collapsed ? "rotate-0" : "rotate-180"
            )}
          />
        </button>
      </div>

      <Link
        href="/chat"
        title={collapsed ? "AIRA-X Home" : undefined}
        className={cn(
          "group mb-5 block border border-[var(--border)] bg-[var(--surface-soft)] shadow-[var(--shadow-soft)] transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]",
          collapsed ? "rounded-2xl p-2" : "rounded-[1.75rem] p-4"
        )}
      >
        <div
          className={cn(
            "flex items-center gap-3",
            collapsed && "justify-center"
          )}
        >
          <div
            className={cn(
              "relative flex items-center justify-center rounded-2xl border border-[var(--border-strong)] bg-[var(--accent-soft)] text-[var(--accent)] shadow-[var(--shadow-soft)] transition duration-200 group-hover:border-[var(--border-strong)]",
              collapsed ? "h-11 w-11" : "h-12 w-12"
            )}
          >
            <Sparkles className="h-5 w-5" />
          </div>

          {!collapsed && (
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-xl font-black tracking-tight text-[var(--text-strong)]">
                  AIRA-X
                </h1>
              </div>

              <p className="mt-1 text-xs font-semibold text-[var(--text-muted)]">
                Research & Execution Platform
              </p>
            </div>
          )}
        </div>

        {!collapsed && (
          

            <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
              AI powered assistant with document retrieval, web research, workflow
            execution, and approval gates.
          </p>
        )}
      </Link>

      {!collapsed && (
        <div className="mb-3 flex items-center justify-between px-2">
          <p className="text-[11px] font-black uppercase tracking-[0.22em] text-[var(--text-subtle)]">
            Workspace
          </p>

          <Activity className="h-3.5 w-3.5 text-[var(--accent)] opacity-80" />
        </div>
      )}

      {collapsed && (
        <div className="mb-3 flex justify-center">
          <Activity className="h-3.5 w-3.5 text-[var(--accent)] opacity-80" />
        </div>
      )}

      <nav
        className={cn(
          "min-h-0 flex-1 space-y-1.5 overflow-y-auto",
          collapsed ? "pr-0" : "pr-1"
        )}
      >
        {navLinks.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={isActivePath(pathname, item)}
            collapsed={collapsed}
          />
        ))}
      </nav>
    </aside>
  );
}
