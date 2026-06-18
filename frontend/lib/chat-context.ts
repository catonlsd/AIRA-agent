// Chat context handoff — bring prior documents, artifacts, and runs back into the
// conversation explicitly, now as a small MULTI-ITEM set plus reusable bundles.
// Server-backed: references are parked on the chat session (no file contents in
// the browser, no blobs in the URL), so the composer can show calm pills and
// prefill an honest starter. Scope-aware (same auth + workspace headers).
// Dependency-free so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ContextAction = "use_as_context" | "revise" | "continue_from" | "retry" | "resume";

export type AttachedContext = {
  ref_type: "document" | "artifact" | "run";
  ref_id: string;
  title: string;
  action: ContextAction;
  role?: string;
  summary: string;
  prompt: string;
  download_url?: string | null;
};

export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };
export type ContextState = { items: AttachedContext[]; prompt: string };

export type Bundle = {
  id: string;
  name: string;
  count: number;
  items: { ref_type: string; title: string }[];
  created_at: string | null;
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

const _VERB: Record<ContextAction, string> = {
  use_as_context: "Using document",
  revise: "Revising artifact",
  continue_from: "Continuing from run",
  retry: "Retrying run",
  resume: "Resuming run",
};

/** A calm, honest pill label — "Revising artifact: Roadmap Deck". */
export function contextLabel(ctx: AttachedContext): string {
  return `${_VERB[ctx.action] ?? "Using"}: ${ctx.title}`;
}

/** The short verb for compact UI (e.g. a chip prefix). */
export function actionVerb(action: ContextAction): string {
  return _VERB[action] ?? "Using";
}

/** The action label shown on a resource's "use in chat" button, per resource. */
export function inChatActionLabel(refType: AttachedContext["ref_type"], action?: ContextAction): string {
  if (refType === "document") return "Use in chat";
  if (refType === "artifact") return "Revise";
  return action === "resume" ? "Resume" : action === "retry" ? "Retry" : "Continue";
}

/** A calm summary for the attached-context header — one label or "Using N items". */
export function itemsSummary(items: AttachedContext[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return contextLabel(items[0]);
  return `Using ${items.length} items`;
}

export function hasItems(items: AttachedContext[] | null | undefined): boolean {
  return Boolean(items && items.length > 0);
}

/** Back-compat single-item check (one attached item is "context"). */
export function hasContext(ctx: AttachedContext | null | undefined): boolean {
  return Boolean(ctx && ctx.ref_id);
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

/** Attach one reference. Returns the clean item, or null when inaccessible. */
export async function attachContext(
  refType: string,
  refId: string,
  sessionId: string
): Promise<AttachedContext | null> {
  const res = await fetch(`${API_URL}/chat/context`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(true),
    body: JSON.stringify({ ref_type: refType, ref_id: refId, session_id: sessionId }),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.context as AttachedContext) ?? null;
}

export async function fetchContext(sessionId: string): Promise<ContextState> {
  const res = await fetch(`${API_URL}/chat/context?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return { items: [], prompt: "" };
  const body = await res.json();
  return { items: Array.isArray(body?.items) ? body.items : [], prompt: body?.prompt ?? "" };
}

export async function removeContextItem(refType: string, refId: string, sessionId: string): Promise<boolean> {
  const params = new URLSearchParams({ ref_type: refType, ref_id: refId, session_id: sessionId });
  const res = await fetch(`${API_URL}/chat/context/item?${params.toString()}`, {
    method: "DELETE",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  return res.ok;
}

export async function clearContext(sessionId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/chat/context?session_id=${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  return res.ok;
}

// ── Bundles ──────────────────────────────────────────────────────────────────

export async function fetchBundles(sessionId: string): Promise<Bundle[]> {
  const res = await fetch(`${API_URL}/bundles?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.bundles) ? body.bundles : [];
}

/** Save the currently attached items as a named bundle. Returns it, or null. */
export async function createBundle(name: string, sessionId: string): Promise<Bundle | null> {
  const res = await fetch(`${API_URL}/bundles`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(true),
    body: JSON.stringify({ name, session_id: sessionId }),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.bundle as Bundle) ?? null;
}

/** Load a bundle's references into the current chat context (re-resolved). */
export async function loadBundle(bundleId: string, sessionId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/bundles/${encodeURIComponent(bundleId)}/load`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(true),
    body: JSON.stringify({ session_id: sessionId }),
  });
  return res.ok;
}

export async function deleteBundle(bundleId: string, sessionId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/bundles/${encodeURIComponent(bundleId)}?session_id=${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  return res.ok;
}
