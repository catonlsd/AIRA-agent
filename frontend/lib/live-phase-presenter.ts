// Live phase presenter for streaming turns.
//
// Turns the incremental SSE events AIRA-X emits while it works (classified mode,
// then ordered `stage` events) into a stable, user-facing phase model. Pure
// functions — no React, no network. Two hard rules:
//   1. Raw backend stage/event names NEVER reach the UI. An unknown stage maps
//      to null and the caller keeps the previous phase — no enum leaks on screen.
//   2. Labels are calm and truthful. A phase is only shown because the backend
//      actually reported it; nothing here invents or animates fake progress.
//
// This complements execution-presenter.ts, which renders the FINAL persisted
// turn. This module drives the ACTIVE (streaming) turn, live.

export type LivePhaseKey =
  | "routing"
  | "understanding"
  | "reading"
  | "researching"
  | "comparing"
  | "writing"
  | "planning"
  | "awaiting_approval"
  | "executing"
  | "validating"
  | "starting_app"
  | "readiness"
  | "healthcheck"
  | "repairing"
  | "retrying"
  | "completed"
  | "failed"
  | "skipped"
  // Queued/background work (durable jobs) — same vocabulary so inline and queued
  // work read as one product.
  | "queued"
  | "working_background"
  | "canceling"
  | "canceled";

export type LiveTone = "active" | "good" | "warn" | "bad";

export type LivePhase = { key: LivePhaseKey; label: string; tone: LiveTone };

const PHASES: Record<LivePhaseKey, { label: string; tone: LiveTone }> = {
  routing: { label: "Routing your request", tone: "active" },
  understanding: { label: "Understanding your request", tone: "active" },
  reading: { label: "Reading your documents", tone: "active" },
  researching: { label: "Researching sources", tone: "active" },
  comparing: { label: "Comparing findings", tone: "active" },
  writing: { label: "Writing the answer", tone: "active" },
  planning: { label: "Planning the work", tone: "active" },
  awaiting_approval: { label: "Waiting for your approval", tone: "warn" },
  executing: { label: "Executing steps", tone: "active" },
  validating: { label: "Running validation", tone: "active" },
  starting_app: { label: "Starting the generated app", tone: "active" },
  readiness: { label: "Waiting for readiness", tone: "active" },
  healthcheck: { label: "Checking health", tone: "active" },
  repairing: { label: "Repairing an issue", tone: "warn" },
  retrying: { label: "Retrying validation", tone: "active" },
  completed: { label: "Completed", tone: "good" },
  failed: { label: "Could not complete", tone: "bad" },
  skipped: { label: "Completed — some checks skipped", tone: "good" },
  queued: { label: "Queued", tone: "active" },
  working_background: { label: "Working in the background", tone: "active" },
  canceling: { label: "Canceling", tone: "warn" },
  canceled: { label: "Canceled", tone: "warn" },
};

function phase(key: LivePhaseKey): LivePhase {
  return { key, ...PHASES[key] };
}

// Backend `stage` strings -> phase. Kept as a flat lookup so new backend stages
// are a one-line addition and an unmapped stage degrades to "keep current phase"
// rather than leaking a raw name.
const STAGE_TO_KEY: Record<string, LivePhaseKey> = {
  // routing / research / answer composition
  clarifying: "understanding",
  reading_documents: "reading",
  collecting_sources: "researching",
  researching: "researching",
  document_fallback_research: "researching",
  comparing_findings: "comparing",
  generating_answer: "writing",
  // planning + approval gates
  planning: "planning",
  plan_ready: "awaiting_approval",
  awaiting_action_approval: "awaiting_approval",
  // execution
  executing_workflow: "executing",
  executing_step: "executing",
  step_repaired: "executing",
  // validation
  validation: "validating",
  validating: "validating",
  // startup / boot verification (Python + Node/Next)
  startup_validation_started: "starting_app",
  waiting_for_ready: "readiness",
  healthcheck_probing: "healthcheck",
  // repair / retry
  repairing: "repairing",
  step_repairing: "repairing",
  retrying: "retrying",
};

const MODE_TO_KEY: Record<string, LivePhaseKey> = {
  web_research: "researching",
  document_qa: "reading",
  execution: "executing",
  research_then_execution: "researching",
  self_memory: "routing",
  general_chat: "writing",
  clarification: "understanding",
};

/** Phase for a streamed backend `stage` event. Null when the stage is unknown
 *  (caller should keep the previous phase — never render the raw name). */
export function livePhaseForStage(stage: string | null | undefined): LivePhase | null {
  if (!stage) return null;
  const key = STAGE_TO_KEY[stage];
  return key ? phase(key) : null;
}

/** Initial phase for a `classified` routing event. */
export function livePhaseForMode(mode: string | null | undefined): LivePhase | null {
  if (!mode) return null;
  const key = MODE_TO_KEY[mode];
  return key ? phase(key) : null;
}

/** Terminal phase from the final turn's status/decision. Overrides any live
 *  phase so the stream resolves to a single honest end state. */
export function finalLivePhase(
  status: string | null | undefined,
  decision: string | null | undefined
): LivePhase {
  const s = status ?? "";
  const d = decision ?? "";
  if (s === "plan_ready" || s === "awaiting_action_approval") return phase("awaiting_approval");
  if (s === "failed" || d.endsWith("_failed") || d === "artifact_rejected") {
    return d === "artifact_rejected" ? phase("skipped") : phase("failed");
  }
  if (d === "plan_executed" && s === "completed") return phase("skipped");
  return phase("completed");
}

export type SSELiteEvent = { type: string; data?: Record<string, unknown> | null };

/**
 * Reduce one streamed SSE event into the live phase. Only `trace` events move
 * the phase; tokens/sources/etc. leave it untouched. Unknown stages keep the
 * current phase. Pure — returns the next phase (or the previous one unchanged).
 */
export function reduceLivePhase(prev: LivePhase | null, event: SSELiteEvent): LivePhase | null {
  if (event.type !== "trace") return prev;
  const data = event.data ?? {};
  const kind = typeof data.event === "string" ? data.event : "";
  if (kind === "classified") {
    return livePhaseForMode(typeof data.mode === "string" ? data.mode : null) ?? prev;
  }
  if (kind === "stage") {
    return livePhaseForStage(typeof data.stage === "string" ? data.stage : null) ?? prev;
  }
  return prev;
}
