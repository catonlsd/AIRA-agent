// Recent activity client for the active scope. Meaningful product events —
// artifacts created, documents uploaded, runs completed/failed, validations,
// preference changes, members added — NOT raw traces. One read, scope-aware
// (rides the same auth + workspace headers), clean UI-ready fields only.
// Dependency-free so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ActivityEvent = {
  type: string;
  title: string;
  actor: string | null;
  status: string | null;
  severity: "info" | "warn";
  resource_type: string | null;
  created_at: string | null;
};

export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };
export type RecentActivity = { scope: ScopeInfo; events: ActivityEvent[] };

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** "Alice · Created a deck" style attribution line (calm, no internals). */
export function eventLine(event: ActivityEvent): string {
  return event.actor ? `${event.actor} · ${event.title}` : event.title;
}

/** Whether an event reads as a problem (drives a subtle warn dot). */
export function isWarn(event: ActivityEvent): boolean {
  return event.severity === "warn";
}

export function hasActivity(a: RecentActivity | null | undefined): boolean {
  return Boolean(a && a.events.length > 0);
}

// ── API client ───────────────────────────────────────────────────────────────

function scopedHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = window.localStorage.getItem("aira_auth_token");
    const workspace = window.localStorage.getItem("aira_active_workspace");
    return {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspace ? { "X-Workspace-Id": workspace } : {}),
    };
  } catch {
    return {};
  }
}

export async function fetchRecentActivity(sessionId: string): Promise<RecentActivity> {
  const res = await fetch(`${API_URL}/activity/recent?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) throw new Error(`Activity request failed (${res.status})`);
  const body = (await res.json()) as RecentActivity;
  return {
    scope: body?.scope ?? { kind: "account", label: "Personal", is_workspace: false },
    events: Array.isArray(body?.events) ? body.events : [],
  };
}
