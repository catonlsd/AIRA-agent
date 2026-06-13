// Presentation layer for execution turns: maps raw backend status/metadata
// into clean, user-facing progress states, approval descriptions, evidence
// summaries, and document provenance. Pure functions — no React, no coupling
// of raw payloads to presentation.

export type PhaseState = "done" | "active" | "failed" | "pending";
export type ExecutionPhase = { key: string; label: string; state: PhaseState };

type Meta = Record<string, any>;

const FRIENDLY_ACTION_LABELS: Record<string, string> = {
  install: "Install dependencies",
  smoke_test: "Run compile check",
  import_smoke: "Run startup smoke test",
  build: "Build / type-check the project",
  healthcheck: "Run healthcheck",
};

/** Friendly description for a runtime action — never raw enums or commands. */
export function describeRuntimeAction(action: {
  type?: string;
  description?: string;
  payload?: { command?: string };
}): string {
  return (
    FRIENDLY_ACTION_LABELS[action.type ?? ""] ??
    action.description ??
    "Run a validation step"
  );
}

/** True when this turn is part of the guided execution flow. */
export function isExecutionTurn(meta: Meta | undefined): boolean {
  if (!meta) return false;
  return Boolean(
    meta.execution_plan ||
      meta.runtime ||
      meta.files_written ||
      meta.runtime_actions ||
      meta.artifact_pending ||
      meta.artifact
  );
}

/** A completed/validated artifact ready for the result card. */
export type ArtifactView = {
  type: string;
  title: string;
  subtitle: string | null;
  filename: string;
  downloadUrl: string | null;
  summary: string; // "8 slides" / "5 sections, 18 paragraphs" / "20 rows × 4 columns"
  sizeLabel: string | null;
  validated: boolean;
  saveLocation: string;
  externalNote: string | null;
};

function _humanSize(bytes: unknown): string | null {
  const n = typeof bytes === "number" ? bytes : 0;
  if (!n) return null;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function presentArtifact(meta: Meta | undefined): ArtifactView | null {
  const art = meta?.artifact;
  if (!art) return null;
  const details = art.validation?.details ?? {};
  const fallbackExtent =
    art.type === "pptx"
      ? `${details.slides ?? "?"} slides`
      : art.type === "docx"
      ? `${details.paragraphs ?? "?"} paragraphs`
      : `${details.rows ?? "?"} rows`;
  const externalNote =
    art.location === "external" && art.requested_path
      ? `Couldn't write to ${art.requested_path} directly — saved to the workspace download area.`
      : null;
  return {
    type: String(art.type ?? "").toUpperCase(),
    title: art.title ?? art.filename ?? "Artifact",
    subtitle: art.subtitle || null,
    filename: art.filename ?? "",
    downloadUrl: art.download_url ?? null,
    summary: art.summary || fallbackExtent,
    sizeLabel: _humanSize(art.size_bytes),
    validated: Boolean(art.validation?.valid),
    saveLocation: art.location === "external" ? "Workspace download area" : "Saved to workspace",
    externalNote,
  };
}

/**
 * Map backend status/decision onto the user-facing phase stepper.
 * Returns null for non-execution turns.
 */
export function presentExecutionPhases(meta: Meta | undefined): ExecutionPhase[] | null {
  if (!isExecutionTurn(meta)) return null;
  const status = String(meta?.turn_status ?? "");
  const decision = String(meta?.turn_decision ?? "");
  const repaired = Array.isArray(meta?.runtime?.repairs) && meta!.runtime.repairs.length > 0;

  const make = (
    plan: PhaseState,
    execute: PhaseState,
    validate: PhaseState,
    done: PhaseState,
    doneLabel = "Completed"
  ): ExecutionPhase[] => [
    { key: "plan", label: "Plan", state: plan },
    { key: "execute", label: "Execute", state: execute },
    {
      key: "validate",
      label: repaired ? "Validate & repair" : "Validate",
      state: validate,
    },
    { key: "done", label: doneLabel, state: done },
  ];

  if (status === "plan_ready") {
    return make("done", "pending", "pending", "pending").map((p) =>
      p.key === "execute" ? { ...p, label: "Waiting for your approval", state: "active" } : p
    );
  }
  if (status === "awaiting_action_approval") {
    return make("done", "done", "active", "pending").map((p) =>
      p.key === "validate" ? { ...p, label: "Validation — awaiting approval" } : p
    );
  }
  if (decision === "runtime_validated" || decision === "artifact_generated") {
    return make("done", "done", "done", "done");
  }
  if (decision === "artifact_rejected") {
    return make("done", "done", "done", "done", "Not generated").map((p) =>
      p.key === "done" ? { ...p, state: "pending" } : p
    );
  }
  if (decision === "artifact_generation_failed") {
    return make("done", "done", "pending", "pending").map((p) => {
      if (p.key === "validate") return { ...p, state: "failed" };
      if (p.key === "done") return { ...p, label: "Could not complete", state: "failed" };
      return p;
    });
  }
  if (decision === "plan_executed" && status === "completed") {
    // Runtime validation skipped by choice — say so honestly.
    return make("done", "done", "done", "done", "Completed (validation skipped)");
  }
  if (status === "failed") {
    const failsAt = decision === "runtime_validation_failed" ? "validate" : "execute";
    return make("done", "done", "pending", "pending").map((p) => {
      if (p.key === failsAt) return { ...p, state: "failed" };
      if (p.key === "done") return { ...p, label: "Could not complete", state: "failed" };
      return p;
    });
  }
  return null;
}

/** Compact evidence chips for finished execution turns. */
export function summarizeEvidence(
  meta: Meta | undefined
): { label: string; tone: "good" | "warn" | "bad" }[] {
  if (!meta) return [];
  const chips: { label: string; tone: "good" | "warn" | "bad" }[] = [];
  const files = Array.isArray(meta.files_written) ? meta.files_written.length : 0;
  if (files > 0) chips.push({ label: `${files} file${files === 1 ? "" : "s"} created`, tone: "good" });

  const summary = meta.runtime?.validation_summary;
  if (summary) {
    if (summary.passed > 0) chips.push({ label: `${summary.passed} check${summary.passed === 1 ? "" : "s"} passed`, tone: "good" });
    if (summary.failed > 0) chips.push({ label: `${summary.failed} check${summary.failed === 1 ? "" : "s"} failed`, tone: "bad" });
  }
  const repairs = Array.isArray(meta.runtime?.repairs) ? meta.runtime.repairs.length : 0;
  if (repairs > 0) chips.push({ label: `${repairs} issue${repairs === 1 ? "" : "s"} repaired`, tone: "warn" });

  // Startup/health verification (only when it really ran).
  const startup = meta.runtime?.startup;
  if (startup?.attempted) {
    if (startup.success) {
      chips.push({ label: `app booted · health ${startup.probe_status ?? "OK"}`, tone: "good" });
    } else {
      chips.push({ label: `startup ${startup.classification ?? "failed"}`, tone: "bad" });
    }
  }
  return chips;
}

/** Clean provenance line for document-first answers (no vector internals). */
export function provenanceLabel(answeredFrom: string | undefined): string | null {
  if (answeredFrom === "uploaded_documents") return "Answered from your uploaded files";
  if (answeredFrom === "web_fallback")
    return "Your files didn't cover this — broader research was used";
  if (answeredFrom === "insufficient_documents")
    return "Not found in your uploaded files";
  return null;
}
