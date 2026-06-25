// Unified live status — one calm phase model for inline AND queued work.
//
// The backend computes a curated `phase` ({key,label,tone}) for every durable
// job, using the SAME vocabulary the streaming presenter uses for inline turns,
// so background work reads identically to live chat work — no second "system".
// This module bridges a queued Job into the shared LivePhase shape and provides
// reconnect helpers, so a reloaded client can restore the right phase from the
// durable snapshot (never fake resumed progress, never a stale banner).
//
// Dependency-free at runtime: the LivePhase types are imported type-only (erased),
// so the pure helpers unit-test cleanly under node --test.

import type { LivePhase, LivePhaseKey, LiveTone } from "./live-phase-presenter";
import type { Job, JobStatus } from "./jobs";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type RunLiveStatus = {
  id: string;
  kind: "job";
  state: "active" | "terminal";
  status: JobStatus;
  phase: { key: string; label: string; tone: LiveTone };
  title: string | null;
  result: Job["result"];
  can_cancel?: boolean;
  can_retry?: boolean;
  updated_at?: string | null;
};

// Fallback mapping when a job dict predates server-computed phases. Mirrors the
// backend so the two never drift in label/tone.
const _STATUS_PHASE: Record<JobStatus, { key: LivePhaseKey; label: string; tone: LiveTone }> = {
  queued: { key: "queued", label: "Queued", tone: "active" },
  running: { key: "working_background", label: "Working in the background", tone: "active" },
  awaiting_approval: { key: "awaiting_approval", label: "Waiting for your approval", tone: "warn" },
  validating: { key: "validating", label: "Running validation", tone: "active" },
  repairing: { key: "repairing", label: "Repairing an issue", tone: "warn" },
  cancel_requested: { key: "canceling", label: "Canceling", tone: "warn" },
  canceled: { key: "canceled", label: "Canceled", tone: "warn" },
  completed: { key: "completed", label: "Completed", tone: "good" },
  failed: { key: "failed", label: "Could not complete", tone: "bad" },
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

const _TERMINAL: JobStatus[] = ["completed", "failed", "canceled"];

/** The unified LivePhase for a job — prefers the server-computed phase, falls
 *  back to a status map (and honours a just-queued retry as "Retrying"). */
export function jobLivePhase(job: Job): LivePhase {
  if (job.phase) {
    return { key: job.phase.key as LivePhaseKey, label: job.phase.label, tone: job.phase.tone };
  }
  if (job.status === "queued" && job.origin === "retry") {
    return { key: "retrying", label: "Retrying", tone: "active" };
  }
  const p = _STATUS_PHASE[job.status] ?? _STATUS_PHASE.running;
  return { key: p.key, label: p.label, tone: p.tone };
}

/** Whether a job is still live (drives whether a live banner should show). */
export function isLiveJob(job: Pick<Job, "status">): boolean {
  return !_TERMINAL.includes(job.status);
}

/** One calm banner label for the active background work, or null when idle. */
export function liveBannerLabel(jobs: Job[]): string | null {
  const live = jobs.filter(isLiveJob);
  if (live.length === 0) return null;
  if (live.length === 1) return jobLivePhase(live[0]).label;
  return `Working in the background · ${live.length} tasks`;
}

/** True once a snapshot has reached a final state — stop watching, reconcile. */
export function isResolved(snapshot: Pick<RunLiveStatus, "state">): boolean {
  return snapshot.state === "terminal";
}

// ── API client (reconnect-safe reads) ────────────────────────────────────────

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

/** Active work in scope — what a reloaded client lists to restore a live view. */
export async function fetchActiveLive(sessionId: string): Promise<RunLiveStatus[]> {
  const res = await fetch(`${API_URL}/jobs/live?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return [];
  const body = await res.json();
  return Array.isArray(body?.live) ? body.live : [];
}

/** One job's reconnect-safe snapshot — resume its phase, or see the terminal state. */
export async function fetchLiveSnapshot(jobId: string, sessionId: string): Promise<RunLiveStatus | null> {
  const res = await fetch(`${API_URL}/jobs/${encodeURIComponent(jobId)}/live?session_id=${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
    headers: scopedHeaders(),
  });
  if (!res.ok) return null;
  const body = await res.json();
  return (body?.live as RunLiveStatus) ?? null;
}
