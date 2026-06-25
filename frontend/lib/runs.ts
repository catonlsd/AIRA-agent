// Run history + chat-native continuation for the active scope. "Pick up where
// we left off": genuinely resumable pending flows, continuable completed
// artifacts, and honestly-surfaced failures — never raw workflow internals.
// One scope-aware read (same auth + workspace headers), clean UI-ready fields.
// Continuation is a prepared chat prompt the composer sends — resume claims a
// pending flow, continue seeds a fresh on-topic build, retry re-runs a goal.
// Dependency-free so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Where the chat page picks up a continuation prompt (set here, taken there).
const CONTINUATION_KEY = "aira_continuation_prompt";

export type RunKind = "resume" | "continue" | "retry";

export type RunItem = {
  id: string;
  kind: RunKind;
  title: string;
  status: string; // requires_approval | completed | failed
  summary: string;
  resumable: boolean;
  action: string; // Resume | Continue | Retry
  download_url: string | null;
  created_at: string | null;
};

export type ScopeInfo = { kind: string; label: string; is_workspace: boolean };
export type RecentRuns = { scope: ScopeInfo; runs: RunItem[] };
export type Continuation = { mode: RunKind; run_id: string; prompt: string; title: string };

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** The honest action label — Resume a paused run, Continue from output, Retry a
 *  failure. Falls back to the server's label, then a sensible default. */
export function actionLabel(run: RunItem): string {
  if (run.action) return run.action;
  return run.kind === "resume" ? "Resume" : run.kind === "retry" ? "Retry" : "Continue";
}

/** Only genuinely pending runs are resumable; everything else continues/retries. */
export function isResumable(run: RunItem): boolean {
  return run.kind === "resume" && run.resumable === true;
}

/** A subtle tone for the status dot — warn for failures, accent otherwise. */
export function runTone(run: RunItem): "warn" | "accent" {
  return run.status === "failed" ? "warn" : "accent";
}

export function hasRuns(r: RecentRuns | null | undefined): boolean {
  return Boolean(r && r.runs.length > 0);
}

// ── Continuation handoff (Settings → chat composer) ──────────────────────────

export function storeContinuation(prompt: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(CONTINUATION_KEY, prompt);
  } catch {
    /* best-effort */
  }
}

/** Read and clear the pending continuation prompt (one-shot). */
export function takeContinuation(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const prompt = window.sessionStorage.getItem(CONTINUATION_KEY);
    if (prompt) window.sessionStorage.removeItem(CONTINUATION_KEY);
    return prompt;
  } catch {
    return null;
  }
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

export async function fetchRecentRuns(sessionId: string): Promise<RecentRuns> {
  const res = await fetch(`${API_URL}/runs/recent?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) throw new Error(`Runs request failed (${res.status})`);
  const body = (await res.json()) as RecentRuns;
  return {
    scope: body?.scope ?? { kind: "account", label: "Personal", is_workspace: false },
    runs: Array.isArray(body?.runs) ? body.runs : [],
  };
}

/** Ask the backend (scope-checked) to prepare a continuation, then hand the
 *  prompt to the chat composer. Returns the prepared continuation. */
export async function continueRun(runId: string, sessionId: string): Promise<Continuation> {
  const res = await fetch(
    `${API_URL}/runs/${encodeURIComponent(runId)}/continue?session_id=${encodeURIComponent(sessionId)}`,
    { method: "POST", cache: "no-store", headers: scopedHeaders() }
  );
  if (!res.ok) throw new Error(`Continue request failed (${res.status})`);
  const body = (await res.json()) as Continuation;
  storeContinuation(body.prompt);
  return body;
}
