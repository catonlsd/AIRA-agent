// Recent shared-resource client for the active scope. One read returns the
// artifacts, documents, and runs visible in the active scope (Personal or a
// workspace) — the backend resolves the scope from the same auth + workspace
// headers everything else uses, so this surface always matches the active scope.
// Kept dependency-free (inline headers) so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ArtifactRef = {
  title: string;
  filename: string;
  type: string;
  size: string | null;
  created_at: string;
  download_url: string;
};

export type DocumentRef = { name: string; type: string; chunks: number; created_at: string | null };
export type RunRef = { label: string; status: string; source: string | null; created_at: string | null };
export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };
export type RecentResources = { scope: ScopeInfo; artifacts: ArtifactRef[]; documents: DocumentRef[]; runs: RunRef[] };

const EMPTY: RecentResources = {
  scope: { kind: "account", label: "Personal", is_workspace: false },
  artifacts: [], documents: [], runs: [],
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** A calm relative time ("just now", "5m ago", "3h ago", "2d ago"). */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** True when a scope has nothing to show yet (drives the clean empty state). */
export function isEmpty(r: RecentResources | null | undefined): boolean {
  return !r || (r.artifacts.length === 0 && r.documents.length === 0 && r.runs.length === 0);
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

export async function fetchRecentResources(sessionId: string): Promise<RecentResources> {
  const res = await fetch(`${API_URL}/resources/recent?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) throw new Error(`Resources request failed (${res.status})`);
  const body = (await res.json()) as RecentResources;
  return {
    scope: body?.scope ?? EMPTY.scope,
    artifacts: Array.isArray(body?.artifacts) ? body.artifacts : [],
    documents: Array.isArray(body?.documents) ? body.documents : [],
    runs: Array.isArray(body?.runs) ? body.runs : [],
  };
}

export const API_BASE = API_URL;
