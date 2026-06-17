// Scoped search + pinned work for the active scope. Find prior artifacts,
// documents, runs, and activity, and keep important items one click away — all
// scope-aware (same auth + workspace headers) and permission-aware on the server.
// Results are clean, UI-ready, and carry a download/continue affordance plus a
// pin reference where the underlying resource supports one. Dependency-free so
// the pure helpers unit-test cleanly (no transitive local imports).

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };

export type SearchResult = {
  result_type: "artifact" | "document" | "run" | "activity";
  title: string;
  summary: string;
  status: string | null;
  created_at: string | null;
  download_url: string | null;
  ref_type?: "artifact" | "run" | "document";
  ref_id?: string;
  run_kind?: "resume" | "continue" | "retry";
  action?: string;
  resumable?: boolean;
};

export type SearchResults = { scope: ScopeInfo; results: SearchResult[] };

export type Pin = {
  id: string;
  ref_type: "artifact" | "run" | "document";
  ref_id: string;
  title: string;
  subtitle: string | null;
  created_at: string | null;
  download_url?: string | null;
  status?: string | null;
  run_kind?: "resume" | "continue" | "retry";
  action?: string;
  resumable?: boolean;
};

export type Pins = { scope: ScopeInfo; pins: Pin[] };

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** The honest action for a result: download an artifact, run-action for a run,
 *  open a document. Activity is informational (no primary action). */
export function resultActionLabel(r: SearchResult): string | null {
  if (r.result_type === "artifact") return "Download";
  if (r.result_type === "run") return r.action || "Continue";
  if (r.result_type === "document") return "Open";
  return null;
}

/** Only resource-backed results (with a ref) can be pinned — activity can't. */
export function canPin(r: SearchResult): boolean {
  return Boolean(r.ref_type && r.ref_id);
}

/** The pin reference for a result, or null when it isn't pinnable. */
export function pinRefFor(r: SearchResult): { ref_type: string; ref_id: string; title: string; subtitle: string } | null {
  if (!r.ref_type || !r.ref_id) return null;
  return { ref_type: r.ref_type, ref_id: r.ref_id, title: r.title, subtitle: r.summary };
}

/** Pins/runs that are genuinely resumable (drives a primary-styled button). */
export function isResumable(item: { run_kind?: string; resumable?: boolean }): boolean {
  return item.run_kind === "resume" && item.resumable === true;
}

export function hasResults(r: SearchResults | null | undefined): boolean {
  return Boolean(r && r.results.length > 0);
}

// ── API client ───────────────────────────────────────────────────────────────

function scopedHeaders(json = false): Record<string, string> {
  const headers: Record<string, string> = json ? { "Content-Type": "application/json" } : {};
  if (typeof window === "undefined") return headers;
  try {
    const token = window.localStorage.getItem("aira_auth_token");
    const workspace = window.localStorage.getItem("aira_active_workspace");
    if (token) headers.Authorization = `Bearer ${token}`;
    if (workspace) headers["X-Workspace-Id"] = workspace;
  } catch {
    /* best-effort */
  }
  return headers;
}

export async function fetchSearch(query: string, sessionId: string, type?: string): Promise<SearchResults> {
  const params = new URLSearchParams({ q: query, session_id: sessionId });
  if (type) params.set("type", type);
  const res = await fetch(`${API_URL}/search?${params.toString()}`, { cache: "no-store", headers: scopedHeaders() });
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
  const body = (await res.json()) as SearchResults;
  return {
    scope: body?.scope ?? { kind: "account", label: "Personal", is_workspace: false },
    results: Array.isArray(body?.results) ? body.results : [],
  };
}

export async function fetchPins(sessionId: string): Promise<Pins> {
  const res = await fetch(`${API_URL}/pins?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) throw new Error(`Pins request failed (${res.status})`);
  const body = (await res.json()) as Pins;
  return {
    scope: body?.scope ?? { kind: "account", label: "Personal", is_workspace: false },
    pins: Array.isArray(body?.pins) ? body.pins : [],
  };
}

export async function pinResult(r: SearchResult, sessionId: string): Promise<boolean> {
  const ref = pinRefFor(r);
  if (!ref) return false;
  const res = await fetch(`${API_URL}/pins?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(true),
    body: JSON.stringify(ref),
  });
  return res.ok;
}

export async function unpin(pinId: string, sessionId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/pins/${encodeURIComponent(pinId)}?session_id=${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  return res.ok;
}
