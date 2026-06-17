// Chat context handoff — bring a prior document, artifact, or run back into the
// conversation explicitly. Server-backed: the reference is parked on the chat
// session (no file contents in the browser, no blobs in the URL), so the composer
// can show one calm pill and prefill an honest starter. Scope-aware (same auth +
// workspace headers). Dependency-free so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ContextAction = "use_as_context" | "revise" | "continue_from" | "retry" | "resume";

export type AttachedContext = {
  ref_type: "document" | "artifact" | "run";
  ref_id: string;
  title: string;
  action: ContextAction;
  summary: string;
  prompt: string;
  download_url?: string | null;
};

export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };

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
  // run — honor the honest run action
  return action === "resume" ? "Resume" : action === "retry" ? "Retry" : "Continue";
}

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

/** Attach a reference as context for the chat session. Returns the clean context
 *  object, or null when it isn't accessible in the active scope. */
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

export async function fetchContext(sessionId: string): Promise<AttachedContext | null> {
  const res = await fetch(`${API_URL}/chat/context?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.context as AttachedContext) ?? null;
}

export async function clearContext(sessionId: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/chat/context?session_id=${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  return res.ok;
}
