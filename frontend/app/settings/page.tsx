"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Layers3,
  LockKeyhole,
  Bookmark,
  Palette,
  RefreshCw,
  LogOut,
  Plus,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UserCircle,
  Users,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { TimeThemeControl } from "@/components/time-theme-control";
import { cn } from "@/lib/utils";
import { getSessionId } from "@/lib/session";
import {
  fetchMe,
  login,
  logout,
  register,
  type Account,
} from "@/lib/auth";
import {
  getActiveWorkspaceId,
  PERSONAL_SCOPE_LABEL,
  setActiveWorkspaceId,
} from "@/lib/scope";
import {
  addMember,
  canManage,
  createWorkspace,
  listMembers,
  listWorkspaces,
  reconcileActiveId,
  removeMember,
  roleLabel,
  updateMemberRole,
  type Member,
  type Workspace,
} from "@/lib/workspaces";
import {
  API_BASE,
  fetchRecentResources,
  isEmpty as resourcesEmpty,
  relativeTime,
  type RecentResources,
} from "@/lib/resources";
import {
  eventLine,
  fetchRecentActivity,
  isWarn,
  type RecentActivity,
} from "@/lib/activity";
import {
  actionLabel,
  fetchRecentRuns,
  isResumable,
  runTone,
  type RecentRuns,
  type RunItem,
} from "@/lib/runs";
import {
  canPin,
  fetchPins,
  fetchSearch,
  isResumable as resultResumable,
  pinResult,
  resultActionLabel,
  unpin,
  type Pin,
  type SearchResult,
} from "@/lib/search";
import {
  attachContext,
  deleteBundle,
  fetchBundles,
  inChatActionLabel,
  loadBundle,
  type Bundle,
} from "@/lib/chat-context";
import {
  canCancel,
  canRetry,
  cancelJob,
  fetchRecentJobs,
  retryJob,
  type Job,
} from "@/lib/jobs";
import { jobLivePhase } from "@/lib/live-status";
import {
  clearAllPreferences,
  fetchPreferences,
  isForbiddenError,
  lastPreferenceScope,
  removePreference,
  savePreference,
  savedCount,
  type PreferenceItem,
} from "@/lib/preferences";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type RuntimeStatus = "checking" | "online" | "offline";
type ModuleTone = "accent" | "secondary" | "success" | "warning" | "danger";

const systemCards = [
  {
    title: "Agents",
    description:
      "Planner, executor, validator, reflection, memory, routing, and approval-aware specialist modules.",
    href: "/agents",
    icon: BrainCircuit,
    label: "Inspect agents",
    tone: "secondary" as const,
  },
  {
    title: "Tools",
    description:
      "Execution capabilities, action policies, tool boundaries, and risk-aware operations.",
    href: "/tools",
    icon: Wrench,
    label: "Inspect tools",
    tone: "accent" as const,
  },
];

const safetyPolicies = [
  {
    title: "Approval Gates",
    description:
      "Environment-changing actions pause until the user explicitly approves or rejects them.",
  },
  {
    title: "Git Preflight",
    description:
      "Git write and push actions expose branch, diff, commit, and remote context before execution.",
  },
  {
    title: "Safe Rejection",
    description:
      "Rejected commit approvals can trigger cleanup so staged changes are not left behind.",
  },
  {
    title: "Stale Recovery",
    description:
      "Long-running approval processing is recovered safely to prevent duplicate execution.",
  },
];

const executionBoundaries = [
  {
    title: "Conversation Layer",
    description:
      "Handles everyday questions, explanations, coding help, casual replies, and assistant capability guidance.",
    icon: Sparkles,
  },
  {
    title: "Research Layer",
    description:
      "Retrieves uploaded documents, reads sources, summarizes content, and produces citation-aware answers.",
    icon: FileText,
  },
  {
    title: "Execution Layer",
    description:
      "Turns user goals into workflows, calls tools, validates results, and records traceable outputs.",
    icon: Activity,
  },
  {
    title: "Governance Layer",
    description:
      "Separates safe actions from risky operations and routes sensitive execution through approvals.",
    icon: LockKeyhole,
  },
];

const workspaceModules = [
  {
    title: "Assistant",
    description:
      "One unified chat surface for general answers, research, workflow execution, and previous-run followups.",
    href: "/chat",
    icon: Sparkles,
  },
  {
    title: "Knowledge",
    description:
      "Uploaded PDFs, indexed documents, retrieved chunks, and source-grounded context.",
    href: "/documents",
    icon: Database,
  },
  {
    title: "Interactions",
    description:
      "Conversation history, research sessions, and previous assistant responses.",
    href: "/history",
    icon: Layers3,
  },
];

function getRuntimeLabel(status: RuntimeStatus) {
  if (status === "checking") {
    return "Checking";
  }

  if (status === "online") {
    return "Operational";
  }

  return "Offline";
}

function getRuntimeIcon(status: RuntimeStatus) {
  if (status === "checking") {
    return <Clock className="h-4 w-4" />;
  }

  if (status === "online") {
    return <CheckCircle2 className="h-4 w-4" />;
  }

  return <XCircle className="h-4 w-4" />;
}

function getRuntimeClass(status: RuntimeStatus) {
  if (status === "online") {
    return "status-success";
  }

  if (status === "offline") {
    return "status-danger";
  }

  return "status-warning";
}

function formatDateTime(value?: Date | null) {
  if (!value) {
    return "Not checked yet";
  }

  return value.toLocaleString();
}

function getToneSurface(tone: ModuleTone) {
  if (tone === "secondary") {
    return "bg-[var(--secondary-soft)] text-[var(--secondary)]";
  }

  if (tone === "success") {
    return "bg-[var(--success-soft)] text-[var(--success)]";
  }

  if (tone === "warning") {
    return "bg-[var(--warning-soft)] text-[var(--warning)]";
  }

  if (tone === "danger") {
    return "bg-[var(--danger-soft)] text-[var(--danger)]";
  }

  return "bg-[var(--accent-soft)] text-[var(--accent)]";
}

function SectionHeading({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
          {icon}
        </div>

        <div>
          <h2 className="type-heading text-[var(--text-strong)]">
            {title}
          </h2>

          <p className="mt-1 max-w-2xl type-body text-[var(--text-muted)]">
            {description}
          </p>
        </div>
      </div>

      {action}
    </div>
  );
}

function RuntimeHealthCard() {
  const [status, setStatus] = useState<RuntimeStatus>("checking");
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [error, setError] = useState("");

  const checkBackendHealth = useCallback(async () => {
    setStatus("checking");
    setError("");

    try {
      const response = await fetch(`${API_URL}/health`, {
        cache: "no-store",
      });

      setStatus(response.ok ? "online" : "offline");

      if (!response.ok) {
        setError(`Backend returned HTTP ${response.status}.`);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Backend health check failed.";

      setStatus("offline");
      setError(message);
    } finally {
      setLastCheckedAt(new Date());
    }
  }, []);

  useEffect(() => {
    checkBackendHealth();

    const intervalId = window.setInterval(checkBackendHealth, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [checkBackendHealth]);

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Server className="h-5 w-5" />}
        title="Runtime Health"
        description="Backend availability for the unified AIRA-X assistant, research pipeline, and execution workflows."
        action={
          <button
            type="button"
            onClick={checkBackendHealth}
            className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                status === "checking" && "animate-spin"
              )}
            />
            Refresh
          </button>
        }
      />

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="type-label text-[var(--text-subtle)]">
            Backend API
          </p>

          <div
            className={cn(
              "mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-black",
              getRuntimeClass(status)
            )}
          >
            {getRuntimeIcon(status)}
            {getRuntimeLabel(status)}
          </div>
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="type-label text-[var(--text-subtle)]">
            Last Checked
          </p>

          <p className="mt-2 type-body-strong text-[var(--text-strong)]">
            {formatDateTime(lastCheckedAt)}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="type-label text-[var(--text-subtle)]">
            Used By
          </p>

          <p className="mt-2 type-body-strong text-[var(--text-strong)]">
            AIRA-X Assistant
          </p>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-[var(--radius-2xl)] border border-[var(--danger-border)] bg-[var(--danger-soft)] p-4 text-sm leading-[var(--leading-code)] text-[var(--danger)]">
          <strong>Runtime issue:</strong> {error}
        </div>
      )}
    </section>
  );
}

function AccountCard() {
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchMe().then((a) => {
      setAccount(a);
      setReady(true);
    });
  }, []);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setError("");
      try {
        const res = mode === "login" ? await login(email, password) : await register(email, password, name);
        setAccount(res.account);
        setPassword("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        setBusy(false);
      }
    },
    [mode, email, password, name]
  );

  const onSignOut = useCallback(() => {
    logout();
    setAccount(null);
    setEmail("");
  }, []);

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<UserCircle className="h-5 w-5" />}
        title="Account"
        description="Sign in so your preferences, documents, and generated files follow you across devices. Without an account, AIRA-X keeps everything to this browser session."
      />

      {!ready ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
          Checking your session…
        </div>
      ) : account ? (
        <div className="flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)] font-black">
              {(account.display_name || account.email).slice(0, 1).toUpperCase()}
            </div>
            <div>
              <p className="type-heading-xs text-[var(--text-strong)]">{account.display_name}</p>
              <p className="text-xs text-[var(--text-muted)]">{account.email}</p>
              <p className="mt-0.5 text-[11px] font-semibold text-[var(--text-subtle)]">
                Scope: {PERSONAL_SCOPE_LABEL}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <div className="mb-3 flex gap-2">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => { setMode(m); setError(""); }}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-black transition",
                  mode === m
                    ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:text-[var(--text-strong)]"
                )}
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <div className="grid gap-2.5">
            {mode === "register" && (
              <input
                type="text" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Name (optional)" autoComplete="name"
                className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--text-strong)] outline-none focus:border-[var(--accent)]"
              />
            )}
            <input
              type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com" autoComplete="email"
              className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--text-strong)] outline-none focus:border-[var(--accent)]"
            />
            <input
              type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="Password (min 8 characters)" autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--text-strong)] outline-none focus:border-[var(--accent)]"
            />
          </div>

          {error && <p className="mt-2 text-xs font-semibold text-[var(--danger)]">{error}</p>}

          <button
            type="submit" disabled={busy || !email || password.length < 1}
            className="mt-3 inline-flex items-center gap-2 rounded-full border border-[var(--accent)] bg-[var(--accent-soft)] px-4 py-2 text-xs font-black text-[var(--accent)] transition hover:brightness-105 disabled:opacity-60"
          >
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      )}
    </section>
  );
}

function WorkspaceCard() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [newName, setNewName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const active = useMemo(() => workspaces.find((w) => w.id === activeId) ?? null, [workspaces, activeId]);
  const myRole = active?.role ?? null;

  const refresh = useCallback(async () => {
    const me = await fetchMe();
    setSignedIn(Boolean(me));
    if (!me) return;
    const list = await listWorkspaces().catch(() => []);
    setWorkspaces(list);
    const safe = reconcileActiveId(list, getActiveWorkspaceId());
    if (safe !== getActiveWorkspaceId()) setActiveWorkspaceId(safe || null);
    setActiveId(safe);
    if (safe) setMembers(await listMembers(safe).catch(() => []));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const switchScope = useCallback((id: string) => {
    setActiveWorkspaceId(id || null);
    // Reload so every scope-aware surface (preferences, chat) re-resolves under
    // the new scope — guarantees the switcher and backend never drift apart.
    window.location.reload();
  }, []);

  const onCreate = useCallback(async () => {
    if (!newName.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createWorkspace(newName.trim());
      setNewName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create workspace.");
    } finally {
      setBusy(false);
    }
  }, [newName, refresh]);

  const onInvite = useCallback(async () => {
    if (!active || !inviteEmail.trim()) return;
    setBusy(true);
    setError("");
    try {
      setMembers(await addMember(active.id, inviteEmail.trim(), inviteRole));
      setInviteEmail("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add member.");
    } finally {
      setBusy(false);
    }
  }, [active, inviteEmail, inviteRole]);

  const onRole = useCallback(async (accountId: string, role: string) => {
    if (!active) return;
    setError("");
    try {
      setMembers(await updateMemberRole(active.id, accountId, role));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update role.");
    }
  }, [active]);

  const onRemove = useCallback(async (accountId: string) => {
    if (!active) return;
    setError("");
    try {
      setMembers(await removeMember(active.id, accountId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove member.");
    }
  }, [active]);

  if (signedIn === false) return null; // workspaces need an account; the Account card prompts sign-in

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Users className="h-5 w-5" />}
        title="Workspaces"
        description="Switch between Personal and a shared workspace. The active scope drives your answers, documents, and generated files everywhere in AIRA-X."
      />

      {/* Active scope selector */}
      <div className="flex flex-wrap gap-2">
        {[{ id: "", name: PERSONAL_SCOPE_LABEL, role: undefined } as Pick<Workspace, "id" | "name" | "role">, ...workspaces].map((w) => {
          const isActive = (w.id || "") === activeId;
          return (
            <button
              key={w.id || "personal"}
              type="button"
              onClick={() => !isActive && switchScope(w.id)}
              aria-pressed={isActive}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-black transition",
                isActive
                  ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
              )}
            >
              {isActive && <CheckCircle2 className="h-3.5 w-3.5" />}
              {w.name}
              {w.role && w.id === activeId && (
                <span className="text-11 font-bold text-[var(--text-subtle)]">· {roleLabel(w.role)}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Create workspace */}
      <div className="mt-3 flex gap-2">
        <input
          type="text" value={newName} onChange={(e) => setNewName(e.target.value)}
          placeholder="New workspace name"
          className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--text-strong)] outline-none focus:border-[var(--accent)]"
        />
        <button
          type="button" onClick={onCreate} disabled={busy || !newName.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)] disabled:opacity-60"
        >
          <Plus className="h-3.5 w-3.5" />
          Create
        </button>
      </div>

      {error && <p className="mt-2 text-xs font-semibold text-[var(--danger)]">{error}</p>}

      {/* Members — only when a workspace is active */}
      {active && (
        <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
          <p className="mb-3 type-label text-[var(--text-subtle)]">
            {active.name} · Members
          </p>

          <div className="grid gap-2">
            {members.map((m) => (
              <div key={m.account_id} className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate type-body-strong text-[var(--text-strong)]">{m.display_name}</p>
                  <p className="truncate text-xs text-[var(--text-muted)]">{m.email}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {canManage(myRole) ? (
                    <select
                      value={m.role}
                      onChange={(e) => onRole(m.account_id, e.target.value)}
                      className="rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-2 py-1 text-xs font-bold text-[var(--text-muted)]"
                    >
                      {["owner", "editor", "viewer"].map((r) => (
                        <option key={r} value={r}>{roleLabel(r)}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-xs font-bold text-[var(--text-subtle)]">{roleLabel(m.role)}</span>
                  )}
                  {canManage(myRole) && (
                    <button
                      type="button" onClick={() => onRemove(m.account_id)}
                      aria-label={`Remove ${m.email}`}
                      className="text-[var(--text-subtle)] transition hover:text-[var(--danger)]"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {canManage(myRole) ? (
            <div className="mt-3 flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
              <input
                type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="Add by email"
                className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--text-strong)] outline-none focus:border-[var(--accent)]"
              />
              <select
                value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}
                className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-2 py-2 text-xs font-bold text-[var(--text-muted)]"
              >
                {["viewer", "editor", "owner"].map((r) => (
                  <option key={r} value={r}>{roleLabel(r)}</option>
                ))}
              </select>
              <button
                type="button" onClick={onInvite} disabled={busy || !inviteEmail.trim()}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-2 text-xs font-black text-[var(--accent)] transition hover:brightness-105 disabled:opacity-60"
              >
                <Plus className="h-3.5 w-3.5" />
                Add
              </button>
            </div>
          ) : (
            <p className="mt-3 border-t border-[var(--border)] pt-3 text-xs text-[var(--text-subtle)]">
              You have {roleLabel(myRole).toLowerCase()} access. Only an owner can manage members.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function LibraryCard() {
  const router = useRouter();
  const [scopeLabel, setScopeLabel] = useState("your scope");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [pins, setPins] = useState<Pin[]>([]);
  const [bundles, setBundles] = useState<Bundle[]>([]);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const refreshPins = useCallback(async () => {
    try {
      const p = await fetchPins(getSessionId());
      setPins(p.pins);
      setScopeLabel(p.scope.label);
    } catch {
      /* calm: a pin read failure just hides the section */
    }
  }, []);

  const refreshBundles = useCallback(async () => {
    try {
      setBundles(await fetchBundles(getSessionId()));
    } catch {
      /* calm: a bundle read failure just hides the section */
    }
  }, []);

  useEffect(() => {
    void refreshPins();
    void refreshBundles();
  }, [refreshPins, refreshBundles]);

  const onLoadBundle = useCallback(async (id: string) => {
    setBusy(id);
    try {
      if (await loadBundle(id, getSessionId())) router.push("/chat");
      else setBusy(null);
    } catch {
      setBusy(null);
    }
  }, [router]);

  const onDeleteBundle = useCallback(async (id: string) => {
    if (await deleteBundle(id, getSessionId())) await refreshBundles();
  }, [refreshBundles]);

  const runSearch = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const r = await fetchSearch(q, getSessionId());
      setResults(r.results);
      setScopeLabel(r.scope.label);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, [query]);

  // Chat-native reuse: park the resource as scope-checked chat context (revise an
  // artifact, use a document, continue/resume/retry a run), then land in chat
  // where it shows as a removable pill and prefills the honest starter.
  const onUseInChat = useCallback(async (refType: string, refId: string) => {
    setBusy(refId);
    try {
      const ctx = await attachContext(refType, refId, getSessionId());
      if (ctx) router.push("/chat");
      else setBusy(null);
    } catch {
      setBusy(null);
    }
  }, [router]);

  const onPin = useCallback(async (r: SearchResult) => {
    if (await pinResult(r, getSessionId())) await refreshPins();
  }, [refreshPins]);

  const onUnpin = useCallback(async (pinId: string) => {
    if (await unpin(pinId, getSessionId())) await refreshPins();
  }, [refreshPins]);

  const actionChip = (refType: string, refId: string, label: string, primary = false) => (
    <button
      type="button"
      onClick={() => onUseInChat(refType, refId)}
      disabled={busy === refId}
      className={cn(
        "shrink-0 rounded-full border px-3 py-1.5 text-xs font-black transition disabled:opacity-60",
        primary
          ? "border-transparent bg-[var(--accent)] text-[var(--accent-contrast,#fff)] hover:opacity-90"
          : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
      )}
    >
      {busy === refId ? "Opening…" : label}
    </button>
  );

  const resultAction = (r: SearchResult) => {
    if (r.result_type === "document" && r.ref_id) {
      return actionChip("document", r.ref_id, inChatActionLabel("document"));
    }
    if (r.result_type === "run" && r.ref_id) {
      return actionChip("run", r.ref_id, r.action || "Continue", resultResumable(r));
    }
    if (r.result_type === "artifact" && r.ref_id) {
      return (
        <>
          {actionChip("artifact", r.ref_id, inChatActionLabel("artifact"))}
          {r.download_url && (
            <a
              href={`${API_BASE}${r.download_url}`}
              download
              className="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
            >
              Download
            </a>
          )}
        </>
      );
    }
    return null;
  };

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Search className="h-5 w-5" />}
        title="Find &amp; pinned work"
        description={`Search artifacts, documents, runs, and activity in ${scopeLabel} — and keep important work one click away.`}
      />

      <form onSubmit={runSearch} className="mb-4 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${scopeLabel.toLowerCase()}…`}
            className="w-full rounded-full border border-[var(--border)] bg-[var(--surface-soft)] py-2 pl-9 pr-3 text-sm text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)]"
          />
        </div>
        <button
          type="submit"
          disabled={searching}
          className="shrink-0 rounded-full border border-transparent bg-[var(--accent)] px-4 py-2 text-xs font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60"
        >
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="grid gap-3">
        {query.trim() && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="mb-2.5 type-label text-[var(--text-subtle)]">Results</p>
            {results.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">No matches in {scopeLabel}. Try another term.</p>
            ) : (
              <div className="grid gap-2">
                {results.map((r, i) => (
                  <div key={`${r.result_type}-${r.ref_id ?? i}`} className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-1.5 py-0.5 text-11 font-black uppercase text-[var(--text-subtle)]">
                        {r.result_type}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate type-body-strong text-[var(--text-strong)]">{r.title}</p>
                        <p className="truncate text-xs text-[var(--text-muted)]">
                          {r.summary}{r.created_at ? ` · ${relativeTime(r.created_at)}` : ""}
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {resultAction(r)}
                      {canPin(r) && (
                        <button
                          type="button"
                          onClick={() => onPin(r)}
                          title="Pin for later"
                          className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] p-1.5 text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--accent)]"
                        >
                          <Bookmark className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {pins.length > 0 && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="mb-2.5 type-label text-[var(--text-subtle)]">Pinned</p>
            <div className="grid gap-2">
              {pins.map((p) => (
                <div key={p.id} className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <Bookmark className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                    <div className="min-w-0">
                      <p className="truncate type-body-strong text-[var(--text-strong)]">{p.title}</p>
                      {p.subtitle ? <p className="truncate text-xs text-[var(--text-muted)]">{p.subtitle}</p> : null}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {p.ref_type === "artifact" && (
                      <>
                        {actionChip("artifact", p.ref_id, inChatActionLabel("artifact"))}
                        {p.download_url && (
                          <a
                            href={`${API_BASE}${p.download_url}`}
                            download
                            className="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
                          >
                            Download
                          </a>
                        )}
                      </>
                    )}
                    {p.ref_type === "document" && actionChip("document", p.ref_id, inChatActionLabel("document"))}
                    {p.ref_type === "run" && p.action && p.status !== "archived" &&
                      actionChip("run", p.ref_id, p.action, resultResumable(p))}
                    <button
                      type="button"
                      onClick={() => onUnpin(p.id)}
                      title="Unpin"
                      className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] p-1.5 text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--warning)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {bundles.length > 0 && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <p className="mb-2.5 type-label text-[var(--text-subtle)]">Handoff packs</p>
            <div className="grid gap-2">
              {bundles.map((b) => (
                <div key={b.id} className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <Layers3 className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                    <div className="min-w-0">
                      <p className="truncate type-body-strong text-[var(--text-strong)]">{b.name}</p>
                      <p className="truncate text-xs text-[var(--text-muted)]">
                        {b.count} item{b.count === 1 ? "" : "s"}{b.items.length ? ` · ${b.items.map((i) => i.title).join(", ")}` : ""}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => onLoadBundle(b.id)}
                      disabled={busy === b.id}
                      className="shrink-0 rounded-full border border-transparent bg-[var(--accent)] px-3 py-1.5 text-xs font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60"
                    >
                      {busy === b.id ? "Opening…" : "Load"}
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteBundle(b.id)}
                      title="Delete pack"
                      className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] p-1.5 text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--warning)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function RecentResourcesCard() {
  const router = useRouter();
  const [data, setData] = useState<RecentResources | null>(null);
  const [activity, setActivity] = useState<RecentActivity | null>(null);
  const [runs, setRuns] = useState<RecentRuns | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobBusy, setJobBusy] = useState<string | null>(null);
  const [continuing, setContinuing] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "hidden">("loading");

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await fetchRecentJobs(getSessionId()));
    } catch {
      /* calm: a jobs read failure just hides the section */
    }
  }, []);

  useEffect(() => {
    const sid = getSessionId();
    Promise.all([
      fetchRecentResources(sid),
      fetchRecentActivity(sid).catch(() => null),
      fetchRecentRuns(sid).catch(() => null),
      fetchRecentJobs(sid).catch(() => []),
    ])
      .then(([r, a, runHistory, jobList]) => {
        setData(r);
        setActivity(a);
        setRuns(runHistory);
        setJobs(jobList);
        setStatus("ready");
      })
      .catch(() => setStatus("hidden"));
  }, []);

  const onCancelJob = useCallback(async (id: string) => {
    setJobBusy(id);
    try {
      await cancelJob(id, getSessionId());
      await refreshJobs();
    } finally {
      setJobBusy(null);
    }
  }, [refreshJobs]);

  const onRetryJob = useCallback(async (id: string) => {
    setJobBusy(id);
    try {
      await retryJob(id, getSessionId());
      await refreshJobs();
    } finally {
      setJobBusy(null);
    }
  }, [refreshJobs]);

  // Chat-native continuation: park the run as scope-checked chat context, then
  // land the user in chat where it shows as a removable pill and prefills the
  // honest starter (resume / continue / retry).
  const onContinue = useCallback(
    async (run: RunItem) => {
      setContinuing(run.id);
      try {
        const ctx = await attachContext("run", run.id, getSessionId());
        if (ctx) router.push("/chat");
        else setContinuing(null);
      } catch {
        setContinuing(null);
      }
    },
    [router]
  );

  if (status === "hidden" || !data) return null;

  const events = activity?.events ?? [];
  const runItems = runs?.runs ?? [];
  // Show background work that still needs attention — in flight, or failed (so it
  // can be retried). Completed work surfaces via artifacts/activity already.
  const bgJobs = jobs.filter((j) => j.status !== "completed");
  const empty = resourcesEmpty(data) && events.length === 0 && runItems.length === 0 && bgJobs.length === 0;

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Layers3 className="h-5 w-5" />}
        title={`Recent in ${data.scope.label}`}
        description="What happened lately, and the artifacts, documents, and runs in your active scope — pick up where you (or your workspace) left off."
      />

      {empty ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
          Nothing here yet. Generate a deck or upload a document and it&apos;ll show up — for {data.scope.label.toLowerCase()} only.
        </div>
      ) : (
        <div className="grid gap-3">
          {bgJobs.length > 0 && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Background work</p>
              <div className="grid gap-2">
                {bgJobs.map((j) => {
                  const phase = jobLivePhase(j);
                  return (
                  <div key={j.id} className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full",
                          phase.tone === "bad" ? "bg-[var(--warning)]"
                            : phase.tone === "warn" ? "bg-[var(--text-subtle)]"
                            : phase.tone === "good" ? "bg-[var(--success)]"
                            : "animate-pulse bg-[var(--accent)]"
                        )}
                        aria-hidden="true"
                      />
                      <span className="truncate text-xs text-[var(--text-muted)]">
                        <span className="font-semibold text-[var(--text-strong)]">{j.title || "Background task"}</span>
                        {` · ${phase.label}`}
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {canCancel(j) && (
                        <button
                          type="button"
                          onClick={() => onCancelJob(j.id)}
                          disabled={jobBusy === j.id}
                          className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1 text-[11px] font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--warning)] disabled:opacity-60"
                        >
                          {jobBusy === j.id ? "…" : "Cancel"}
                        </button>
                      )}
                      {canRetry(j) && (
                        <button
                          type="button"
                          onClick={() => onRetryJob(j.id)}
                          disabled={jobBusy === j.id}
                          className="rounded-full border border-transparent bg-[var(--accent)] px-2.5 py-1 text-[11px] font-black text-[var(--accent-contrast,#fff)] transition hover:opacity-90 disabled:opacity-60"
                        >
                          {jobBusy === j.id ? "…" : "Retry"}
                        </button>
                      )}
                    </div>
                  </div>
                  );
                })}
              </div>
            </div>
          )}
          {events.length > 0 && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Activity</p>
              <div className="grid gap-1.5">
                {events.slice(0, 8).map((e, i) => (
                  <p key={i} className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        isWarn(e) ? "bg-[var(--warning)]" : "bg-[var(--accent)]"
                      )}
                      aria-hidden="true"
                    />
                    <span className="truncate">
                      <span className="font-semibold text-[var(--text-strong)]">{eventLine(e)}</span>
                      {e.created_at ? ` · ${relativeTime(e.created_at)}` : ""}
                    </span>
                  </p>
                ))}
              </div>
            </div>
          )}
          {data.artifacts.length > 0 && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Artifacts</p>
              <div className="grid gap-2">
                {data.artifacts.map((a) => (
                  <div key={a.filename} className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <FileText className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                      <div className="min-w-0">
                        <p className="truncate type-body-strong text-[var(--text-strong)]">{a.title}</p>
                        <p className="truncate text-xs text-[var(--text-muted)]">
                          {a.type}{a.size ? ` · ${a.size}` : ""} · {relativeTime(a.created_at)}
                        </p>
                      </div>
                    </div>
                    <a
                      href={`${API_BASE}${a.download_url}`} download={a.filename}
                      className="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
                    >
                      Download
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.documents.length > 0 && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Documents</p>
              <div className="grid gap-2">
                {data.documents.map((d, i) => (
                  <div key={`${d.name}-${i}`} className="flex items-center gap-2.5">
                    <Database className="h-4 w-4 shrink-0 text-[var(--secondary)]" />
                    <div className="min-w-0">
                      <p className="truncate type-body-strong text-[var(--text-strong)]">{d.name}</p>
                      <p className="truncate text-xs text-[var(--text-muted)]">
                        {d.type} · {d.chunks} chunk{d.chunks === 1 ? "" : "s"}{d.created_at ? ` · ${relativeTime(d.created_at)}` : ""}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {runItems.length > 0 && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Continue your work</p>
              <div className="grid gap-2">
                {runItems.map((r) => (
                  <div key={r.id} className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full",
                          runTone(r) === "warn" ? "bg-[var(--warning)]" : "bg-[var(--accent)]"
                        )}
                        aria-hidden="true"
                      />
                      <div className="min-w-0">
                        <p className="truncate type-body-strong text-[var(--text-strong)]">{r.title}</p>
                        <p className="truncate text-xs text-[var(--text-muted)]">
                          {r.summary}{r.created_at ? ` · ${relativeTime(r.created_at)}` : ""}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onContinue(r)}
                      disabled={continuing === r.id}
                      className={cn(
                        "shrink-0 rounded-full border px-3 py-1.5 text-xs font-black transition disabled:opacity-60",
                        isResumable(r)
                          ? "border-transparent bg-[var(--accent)] text-[var(--accent-contrast,#fff)] hover:opacity-90"
                          : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
                      )}
                    >
                      {continuing === r.id ? "Opening…" : actionLabel(r)}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PreferencesCard() {
  const [items, setItems] = useState<PreferenceItem[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "offline">("loading");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const [scopeLabelText, setScopeLabelText] = useState("Personal");
  const [restricted, setRestricted] = useState(false);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setItems(await fetchPreferences(getSessionId()));
      setScopeLabelText(lastPreferenceScope()?.label || "Personal");
      setStatus("ready");
    } catch {
      setStatus("offline");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Mutations can be denied (e.g. a viewer editing workspace defaults). Show a
  // calm note and reload, rather than an "offline" error.
  const onMutationError = useCallback((err: unknown) => {
    if (isForbiddenError(err)) {
      setRestricted(true);
      load();
    } else {
      setStatus("offline");
    }
  }, [load]);

  const onSelect = useCallback(async (key: string, value: string, current: string | null) => {
    setBusyKey(key);
    setRestricted(false);
    try {
      // Clicking the active value clears it (toggle off); otherwise set it.
      const next =
        current === value
          ? await removePreference(getSessionId(), key)
          : await savePreference(getSessionId(), key, value);
      setItems(next);
    } catch (err) {
      onMutationError(err);
    } finally {
      setBusyKey(null);
    }
  }, [onMutationError]);

  const onRemove = useCallback(async (key: string) => {
    setBusyKey(key);
    setRestricted(false);
    try {
      setItems(await removePreference(getSessionId(), key));
    } catch (err) {
      onMutationError(err);
    } finally {
      setBusyKey(null);
    }
  }, [onMutationError]);

  const onClearAll = useCallback(async () => {
    setBusyKey("__all__");
    setRestricted(false);
    try {
      setItems(await clearAllPreferences(getSessionId()));
      setConfirmClear(false);
    } catch (err) {
      onMutationError(err);
    } finally {
      setBusyKey(null);
    }
  }, []);

  const count = savedCount(items);

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<SlidersHorizontal className="h-5 w-5" />}
        title="Assistant Preferences"
        description={`Editing ${scopeLabelText} defaults. AIRA-X applies these to your answers and generated files; your current message always overrides them, and you can change or clear them anytime.`}
        action={
          count > 0 && status === "ready" ? (
            confirmClear ? (
              <div className="inline-flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClearAll}
                  disabled={busyKey === "__all__"}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--danger)_40%,transparent)] bg-[var(--danger-soft)] px-3 py-2 text-xs font-black text-[var(--danger)] transition hover:brightness-105"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Confirm clear all
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmClear(false)}
                  className="rounded-full border border-[var(--border)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:text-[var(--text-strong)]"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmClear(true)}
                className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear all
              </button>
            )
          ) : undefined
        }
      />

      {status === "offline" && (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
          Couldn&apos;t reach the assistant to load your preferences. They&apos;ll appear here when it&apos;s back online.
        </div>
      )}

      {restricted && (
        <div className="mb-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-semibold text-[var(--text-muted)]">
          You have view-only access to these {scopeLabelText} defaults — an owner can change them.
        </div>
      )}

      {status === "loading" && (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
          Loading your saved preferences…
        </div>
      )}

      {status === "ready" && (
        <>
          <p className="mb-3 text-xs font-semibold text-[var(--text-subtle)]">
            {count === 0
              ? "No preferences saved yet — pick any below, or just tell AIRA-X in chat (e.g. “keep answers concise”)."
              : `${count} preference${count === 1 ? "" : "s"} saved. Temporary conversation context is separate and isn’t shown here.`}
          </p>

          <div className="grid gap-3">
            {items.map((item) => (
              <div
                key={item.key}
                className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="type-heading-xs text-[var(--text-strong)]">{item.label}</p>
                    <p className="mt-1 type-body-sm text-[var(--text-muted)]">{item.description}</p>
                  </div>
                  {item.value != null && (
                    <button
                      type="button"
                      onClick={() => onRemove(item.key)}
                      disabled={busyKey === item.key}
                      className="shrink-0 text-xs font-bold text-[var(--text-subtle)] transition hover:text-[var(--danger)]"
                      aria-label={`Remove ${item.label} preference`}
                    >
                      Remove
                    </button>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {item.options.map((option) => {
                    const active = item.value === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => onSelect(item.key, option.value, item.value)}
                        disabled={busyKey === item.key}
                        aria-pressed={active}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-black transition",
                          active
                            ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                            : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-strong)]"
                        )}
                      >
                        {active && <CheckCircle2 className="h-3.5 w-3.5" />}
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function AppearanceCard() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Palette className="h-5 w-5" />}
        title="Appearance"
        description="The theme follows your local time of day automatically. Leave it on Auto, or pin a specific period."
      />

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
        <TimeThemeControl />

        <p className="mt-4 type-body-sm text-[var(--text-muted)]">
          Auto cycles through six palettes across the day — pre-dawn, sunrise, daytime,
          dusk, sunset, and night — with a smooth crossfade at each boundary. Pinning a
          period overrides the clock until you switch back to Auto.
        </p>
      </div>
    </section>
  );
}

function ModuleLinkCard({
  title,
  description,
  href,
  icon,
  label,
  tone = "accent",
}: {
  title: string;
  description: string;
  href: string;
  icon: ReactNode;
  label: string;
  tone?: ModuleTone;
}) {
  return (
    <Link
      href={href}
      className="sarvam-card group rounded-[1.5rem] p-5 transition hover:-translate-y-0.5"
    >
      <div className="mb-5 flex items-start justify-between gap-4">
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)]",
            getToneSurface(tone)
          )}
        >
          {icon}
        </div>

        <ArrowRight className="h-4 w-4 text-[var(--text-subtle)] transition group-hover:translate-x-1 group-hover:text-[var(--accent)]" />
      </div>

      <h2 className="type-heading text-[var(--text-strong)]">{title}</h2>

      <p className="mt-2 type-body text-[var(--text-muted)]">
        {description}
      </p>

      <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition group-hover:border-[var(--border-strong)] group-hover:text-[var(--text-strong)]">
        {label}
        <ArrowRight className="h-3.5 w-3.5" />
      </div>
    </Link>
  );
}

function WorkspaceSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<Database className="h-5 w-5" />}
        title="Assistant Workspace"
        description="AIRA-X brings general chat, document-grounded research, workflow execution, and history into one assistant experience."
      />

      <div className="grid gap-3 md:grid-cols-3">
        {workspaceModules.map((module) => {
          const Icon = module.icon;

          return (
            <Link
              key={module.title}
              href={module.href}
              className="group rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 transition hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
            >
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <Icon className="h-4 w-4" />
              </div>

              <div className="flex items-center justify-between gap-2">
                <p className="type-heading-xs text-[var(--text-strong)]">
                  {module.title}
                </p>

                <ArrowRight className="h-3.5 w-3.5 text-[var(--text-subtle)] transition group-hover:translate-x-1 group-hover:text-[var(--accent)]" />
              </div>

              <p className="mt-2 type-body text-[var(--text-muted)]">
                {module.description}
              </p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function SafetyPoliciesSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<ShieldCheck className="h-5 w-5" />}
        title="Safety Policies"
        description="Rules that keep autonomous execution inspectable, reversible, and human-controlled."
      />

      <div className="grid gap-3">
        {safetyPolicies.map((policy) => (
          <div
            key={policy.title}
            className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" />

            <div>
              <p className="type-heading-xs text-[var(--text-strong)]">
                {policy.title}
              </p>

              <p className="mt-1 type-body text-[var(--text-muted)]">
                {policy.description}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExecutionBoundariesSection() {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeading
        icon={<LockKeyhole className="h-5 w-5" />}
        title="System Boundaries"
        description="AIRA-X separates conversation, research, execution, and governance so every response remains understandable and safe."
      />

      <div className="grid gap-3">
        {executionBoundaries.map((boundary) => {
          const Icon = boundary.icon;

          return (
            <div
              key={boundary.title}
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
            >
              <div className="mb-3 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                  <Icon className="h-4 w-4" />
                </div>

                <p className="type-heading-xs text-[var(--text-strong)]">
                  {boundary.title}
                </p>
              </div>

              <p className="type-body text-[var(--text-muted)]">
                {boundary.description}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function SettingsPage() {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              <Sparkles className="h-3.5 w-3.5" />
              Platform settings
            </div>

            <h1 className="aira-gradient-text type-display">
              Settings
            </h1>

            <p className="mt-3 max-w-3xl type-body text-[var(--text-muted)]">
              Configure appearance, runtime health, workspace modules, agent
              policies, tool boundaries, and approval-aware execution rules.
            </p>
          </div>

          <div className="inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold status-success">
            <Activity className="h-3.5 w-3.5" />
            Production workspace
          </div>
        </div>
      </section>

      <AccountCard />

      <WorkspaceCard />

      <RecentResourcesCard />

      <LibraryCard />

      <PreferencesCard />

      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <AppearanceCard />
        <RuntimeHealthCard />
      </section>

      <WorkspaceSection />

      <section className="grid gap-4 md:grid-cols-2">
        {systemCards.map((card) => {
          const Icon = card.icon;

          return (
            <ModuleLinkCard
              key={card.title}
              title={card.title}
              description={card.description}
              href={card.href}
              icon={<Icon className="h-5 w-5" />}
              label={card.label}
              tone={card.tone}
            />
          );
        })}
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <SafetyPoliciesSection />
        <ExecutionBoundariesSection />
      </section>
    </div>
  );
}
