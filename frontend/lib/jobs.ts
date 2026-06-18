// Background job status — reconnect-safe, calm, never a job console. When heavy
// work (e.g. an artifact) runs durably on the worker, the client can ask "is it
// done?" after a disconnect without polling chrome. Scope-aware (same auth +
// workspace headers); results are UI-ready only (status, progress, a clean
// title/download/error). Dependency-free so the pure helpers unit-test cleanly.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type JobStatus =
  | "queued" | "running" | "awaiting_approval" | "validating" | "repairing"
  | "completed" | "failed" | "cancel_requested" | "canceled";

export type JobResult = {
  title?: string;
  type?: string;
  download_url?: string | null;
  summary?: string | null;
  error?: string | null;
} | null;

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  title: string | null;
  progress: string | null;
  result: JobResult;
  origin?: "retry" | "replay" | null;
  can_cancel?: boolean;
  can_retry?: boolean;
  created_at: string | null;
  updated_at: string | null;
};

const _ACTIVE: JobStatus[] = ["queued", "running", "awaiting_approval", "validating", "repairing", "cancel_requested"];
const _CANCELABLE: JobStatus[] = ["queued", "running", "awaiting_approval", "validating", "repairing"];
const _LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Working",
  awaiting_approval: "Awaiting approval",
  validating: "Validating",
  repairing: "Repairing",
  completed: "Ready",
  failed: "Failed",
  cancel_requested: "Canceling",
  canceled: "Canceled",
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** A calm, human status label — never a raw enum or worker id. */
export function jobStatusLabel(status: JobStatus): string {
  return _LABEL[status] ?? "Working";
}

/** Still in flight — drives a calm "working in the background" affordance. */
export function isActive(status: JobStatus): boolean {
  return _ACTIVE.includes(status);
}

/** Reached a final state — safe to stop watching. */
export function isTerminal(status: JobStatus): boolean {
  return !_ACTIVE.includes(status);
}

/** Tone for a status dot: warn on failure, accent while active, muted when done. */
export function jobTone(status: JobStatus): "warn" | "accent" | "muted" {
  if (status === "failed") return "warn";
  if (isActive(status)) return "accent";
  return "muted";
}

/** Whether a Cancel control should be offered (honest: only mid-flight jobs). */
export function canCancel(job: Job): boolean {
  return job.can_cancel ?? _CANCELABLE.includes(job.status);
}

/** Whether a Retry control should be offered (honest: only failed jobs). */
export function canRetry(job: Job): boolean {
  return job.can_retry ?? job.status === "failed";
}

export function hasActiveJobs(jobs: Job[] | null | undefined): boolean {
  return Boolean(jobs && jobs.some((j) => isActive(j.status)));
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

/** One job's current status (reconnect-safe). Null when not visible in scope. */
export async function fetchJob(jobId: string, sessionId: string): Promise<Job | null> {
  const res = await fetch(`${API_URL}/jobs/${encodeURIComponent(jobId)}?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.job as Job) ?? null;
}

export async function fetchRecentJobs(sessionId: string, activeOnly = false): Promise<Job[]> {
  const params = new URLSearchParams({ session_id: sessionId });
  if (activeOnly) params.set("active", "true");
  const res = await fetch(`${API_URL}/jobs?${params.toString()}`, { cache: "no-store", headers: scopedHeaders() });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.jobs) ? body.jobs : [];
}

/** Request cancellation. Returns the honest outcome (status + message), or null. */
export async function cancelJob(jobId: string, sessionId: string): Promise<{ ok: boolean; status: JobStatus | null; message: string } | null> {
  const res = await fetch(`${API_URL}/jobs/${encodeURIComponent(jobId)}/cancel?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return null;
  return res.json();
}

/** Retry a failed job — schedules a real new attempt. Returns the new job, or null. */
export async function retryJob(jobId: string, sessionId: string): Promise<Job | null> {
  const res = await fetch(`${API_URL}/jobs/${encodeURIComponent(jobId)}/retry?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.job as Job) ?? null;
}
