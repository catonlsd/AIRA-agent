"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  CheckCircle2,
  Clock,
  GitBranch,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  Workflow,
  XCircle,
} from "lucide-react";
import {
  approveAiraX,
  getAiraXRuns,
  rejectAiraX,
  type AiraXWorkflowRun,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ApprovalTab = "pending" | "processing" | "resolved" | "all";

const RESOLVED_APPROVAL_STATUSES = new Set([
  "approved",
  "rejected",
  "approved_but_resume_failed",
  "stale_processing_recovered",
]);

function isApprovalProcessing(run?: AiraXWorkflowRun | null) {
  return run?.approval_in_progress === true;
}

function isWaitingForApproval(run: AiraXWorkflowRun) {
  return run.requires_approval || run.status === "requires_approval";
}

function hasApprovalResolution(run: AiraXWorkflowRun) {
  return (
    run.approval_resolution &&
    typeof run.approval_resolution === "object" &&
    Object.keys(run.approval_resolution).length > 0
  );
}

function hasResolvedApproval(run: AiraXWorkflowRun) {
  const status = run.approval_resolution?.status;

  return (
    Boolean(status) &&
    RESOLVED_APPROVAL_STATUSES.has(status || "") &&
    !isWaitingForApproval(run) &&
    !isApprovalProcessing(run)
  );
}

function getApprovalStatus(run: AiraXWorkflowRun) {
  if (isApprovalProcessing(run)) {
    return "processing";
  }

  if (isWaitingForApproval(run)) {
    return "pending";
  }

  if (hasApprovalResolution(run) && run.approval_resolution?.status) {
    return run.approval_resolution.status;
  }

  return "not_required";
}

function getApprovalBadgeClass(status: string) {
  if (status === "approved") {
    return "status-success";
  }

  if (
    status === "rejected" ||
    status === "approved_but_resume_failed" ||
    status === "stale_processing_recovered"
  ) {
    return "status-danger";
  }

  if (status === "pending" || status === "processing" || status === "in_progress") {
    return "status-warning";
  }

  return "status-info";
}

function getApprovalLabel(status: string) {
  if (status === "approved") {
    return "Approved";
  }

  if (status === "rejected") {
    return "Rejected";
  }

  if (status === "approved_but_resume_failed") {
    return "Approved, resume failed";
  }

  if (status === "stale_processing_recovered") {
    return "Stale processing recovered";
  }

  if (status === "processing" || status === "in_progress") {
    return "Processing";
  }

  if (status === "pending") {
    return "Pending approval";
  }

  return "Not required";
}

function getPreflightType(run: AiraXWorkflowRun) {
  return run.approval_context_type || run.approval_context?.type || "";
}

function isGitPushPreflight(run: AiraXWorkflowRun) {
  return getPreflightType(run) === "git_push_preflight";
}

function isGitWritePreflight(run: AiraXWorkflowRun) {
  return getPreflightType(run) === "git_write_preflight";
}

function formatDateTime(value?: string) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function getRunAction(run: AiraXWorkflowRun) {
  return (
    run.approval_resolution?.action ||
    run.approval_resolution_action ||
    run.pending_action ||
    run.approval_context?.pending_action ||
    "No action recorded"
  );
}

function ApprovalMetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "info" | "warning" | "success" | "danger";
}) {
  const toneClass =
    tone === "warning"
      ? "text-[var(--warning)]"
      : tone === "success"
        ? "text-[var(--success)]"
        : tone === "danger"
          ? "text-[var(--danger)]"
          : "text-[var(--accent)]";

  return (
    <div className="sarvam-card rounded-[1.5rem] p-5">
      <p className="text-sm font-semibold text-[var(--text-muted)]">{label}</p>

      <h2 className={cn("mt-1 text-3xl font-black", toneClass)}>{value}</h2>
    </div>
  );
}

function ApprovalCard({
  run,
  actionRunId,
  actionType,
  onApprove,
  onReject,
}: {
  run: AiraXWorkflowRun;
  actionRunId: string | null;
  actionType: "approve" | "reject" | null;
  onApprove: (runId: string) => Promise<void>;
  onReject: (runId: string) => Promise<void>;
}) {
  const approvalStatus = getApprovalStatus(run);
  const waitingForApproval = isWaitingForApproval(run);
  const approvalProcessing = isApprovalProcessing(run);
  const actionInProgress = actionRunId === run.run_id;
  const actionButtonsDisabled = Boolean(actionRunId) || approvalProcessing;
  const gitPushPreflight = isGitPushPreflight(run);
  const gitWritePreflight = isGitWritePreflight(run);
  const context = run.approval_context || {};
  const resolution = run.approval_resolution;

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold",
                getApprovalBadgeClass(approvalStatus)
              )}
            >
              {approvalStatus === "approved" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : approvalStatus === "rejected" ||
                approvalStatus === "approved_but_resume_failed" ||
                approvalStatus === "stale_processing_recovered" ? (
                <XCircle className="h-3.5 w-3.5" />
              ) : approvalStatus === "processing" ? (
                <Clock className="h-3.5 w-3.5" />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5" />
              )}

              {getApprovalLabel(approvalStatus)}
            </span>

            {gitWritePreflight && (
              <span className="inline-flex items-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] px-3 py-1 text-xs font-bold text-[var(--warning)]">
                <GitBranch className="h-3.5 w-3.5" />
                Git Write Preflight
              </span>
            )}

            {gitPushPreflight && (
              <span className="inline-flex items-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-3 py-1 text-xs font-bold text-[var(--danger)]">
                <UploadCloud className="h-3.5 w-3.5" />
                Git Push Preflight
              </span>
            )}

            <span className="rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1 text-xs font-semibold text-[var(--text-muted)]">
              Workflow: {run.status}
            </span>
          </div>

          <Link
            href={`/workflows/${run.run_id}`}
            className="group block"
          >
            <h2 className="truncate text-base font-black text-[var(--text-strong)] group-hover:text-[var(--accent)]">
              {run.user_goal || "Untitled workflow"}
            </h2>

            <p className="mt-1 break-all text-xs text-[var(--text-subtle)]">
              {run.run_id}
            </p>
          </Link>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Approval Action
              </p>

              <p className="mt-1 break-words text-sm font-semibold text-[var(--text-strong)]">
                {getRunAction(run)}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Decision
              </p>

              <p className="mt-1 break-words text-sm font-semibold text-[var(--text-strong)]">
                {run.decision || "Not recorded"}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Requested
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {formatDateTime(resolution?.requested_at)}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Completed
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {formatDateTime(resolution?.completed_at)}
              </p>
            </div>
          </div>

          {(gitWritePreflight || gitPushPreflight) && (
            <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
                {gitPushPreflight ? (
                  <UploadCloud className="h-4 w-4 text-[var(--danger)]" />
                ) : (
                  <GitBranch className="h-4 w-4 text-[var(--warning)]" />
                )}
                Preflight Preview
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                    Current Branch
                  </p>

                  <p className="mt-1 text-sm font-semibold text-[var(--text)]">
                    {context.branch || "Unknown branch"}
                  </p>
                </div>

                <div>
                  <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                    Target
                  </p>

                  <p className="mt-1 text-sm font-semibold text-[var(--text)]">
                    {gitPushPreflight
                      ? `${context.target_remote || "origin"} / ${
                          context.target_branch || context.branch || "unknown"
                        }`
                      : context.commit_message || "Git write action"}
                  </p>
                </div>
              </div>
            </div>
          )}

          {resolution?.error && (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-3 text-sm leading-6 text-[var(--danger)]">
              <strong>Error:</strong> {resolution.error}
            </div>
          )}
        </div>

        {waitingForApproval && (
          <div className="rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-4 xl:w-80">
            <p className="flex items-center gap-2 text-sm font-black text-[var(--warning)]">
              {approvalProcessing ? (
                <Clock className="h-4 w-4" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {approvalProcessing ? "Approval processing" : "Approval required"}
            </p>

            <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
              {approvalProcessing
                ? "AIRA-X is already processing this approval-gated action."
                : "Approve to continue this workflow, or reject to stop it safely."}
            </p>

            <div className="mt-4 flex flex-col gap-2">
              <button
                type="button"
                onClick={() => onApprove(run.run_id)}
                disabled={actionButtonsDisabled}
                className="rounded-xl bg-[var(--warning)] px-4 py-2.5 text-xs font-black text-white shadow-[var(--shadow-soft)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {approvalProcessing
                  ? "Processing..."
                  : actionInProgress && actionType === "approve"
                    ? "Approving..."
                    : "Approve & Continue"}
              </button>

              <button
                type="button"
                onClick={() => onReject(run.run_id)}
                disabled={actionButtonsDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--danger)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <XCircle className="h-3.5 w-3.5" />
                {approvalProcessing
                  ? "Processing..."
                  : actionInProgress && actionType === "reject"
                    ? "Rejecting..."
                    : "Reject Action"}
              </button>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

export default function ApprovalsPage() {
  const [runs, setRuns] = useState<AiraXWorkflowRun[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [activeTab, setActiveTab] = useState<ApprovalTab>("pending");
  const [loading, setLoading] = useState(true);
  const [actionRunId, setActionRunId] = useState<string | null>(null);
  const [actionType, setActionType] = useState<"approve" | "reject" | null>(
    null
  );
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");

  const loadRuns = useCallback(async (options?: { showLoading?: boolean }) => {
    const showLoading = options?.showLoading ?? true;

    try {
      if (showLoading) {
        setLoading(true);
      }

      const data = await getAiraXRuns();

      setRuns(data.runs || []);
      setRunCount(data.run_count || 0);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load approvals.";

      setError(message);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  async function handleApprove(runId: string) {
    const currentRun = runs.find((run) => run.run_id === runId);

    if (isApprovalProcessing(currentRun)) {
      return;
    }

    try {
      setActionRunId(runId);
      setActionType("approve");
      setError("");

      await approveAiraX(runId);
      await loadRuns({ showLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to approve workflow.";

      setError(message);
      await loadRuns({ showLoading: false });
    } finally {
      setActionRunId(null);
      setActionType(null);
    }
  }

  async function handleReject(runId: string) {
    const currentRun = runs.find((run) => run.run_id === runId);

    if (isApprovalProcessing(currentRun)) {
      return;
    }

    try {
      setActionRunId(runId);
      setActionType("reject");
      setError("");

      await rejectAiraX(runId);
      await loadRuns({ showLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to reject workflow.";

      setError(message);
      await loadRuns({ showLoading: false });
    } finally {
      setActionRunId(null);
      setActionType(null);
    }
  }

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const approvalRuns = useMemo(
    () =>
      runs.filter(
        (run) =>
          isWaitingForApproval(run) ||
          isApprovalProcessing(run) ||
          hasResolvedApproval(run)
      ),
    [runs]
  );

  const pendingRuns = approvalRuns.filter(
    (run) => isWaitingForApproval(run) && !isApprovalProcessing(run)
  );
  const processingRuns = approvalRuns.filter((run) => isApprovalProcessing(run));
  const resolvedRuns = approvalRuns.filter((run) => hasResolvedApproval(run));

  const visibleRuns = approvalRuns.filter((run) => {
    if (activeTab === "pending") {
      return pendingRuns.some((pending) => pending.run_id === run.run_id);
    }

    if (activeTab === "processing") {
      return processingRuns.some(
        (processing) => processing.run_id === run.run_id
      );
    }

    if (activeTab === "resolved") {
      return resolvedRuns.some((resolved) => resolved.run_id === run.run_id);
    }

    return true;
  });

  useEffect(() => {
    if (processingRuns.length === 0) {
      setPolling(false);
      return;
    }

    setPolling(true);

    const intervalId = window.setInterval(() => {
      loadRuns({ showLoading: false });
    }, 2000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [processingRuns.length, loadRuns]);

  const tabs: { id: ApprovalTab; label: string; count: number }[] = [
    { id: "pending", label: "Pending", count: pendingRuns.length },
    { id: "processing", label: "Processing", count: processingRuns.length },
    { id: "resolved", label: "Resolved", count: resolvedRuns.length },
    { id: "all", label: "All", count: approvalRuns.length },
  ];

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative rounded-[1.75rem] p-6">
        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-3 px-3 py-1.5 text-xs font-bold">
              <ShieldCheck className="h-3.5 w-3.5" />
              Human-gated execution
            </div>

            <h1 className="aira-gradient-text text-3xl font-black tracking-tight">
              Approvals
            </h1>

            <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-muted)]">
              Review approval-gated actions before AIRA-X modifies the
              environment, writes Git history, or pushes to a remote repository.
            </p>
          </div>

          {polling && (
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-3 py-1.5 text-xs font-bold text-[var(--accent)]">
              <Activity className="h-3.5 w-3.5" />
              Auto-refreshing
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-5">
        <ApprovalMetricCard label="Total Runs" value={runCount} tone="info" />
        <ApprovalMetricCard
          label="Approval Runs"
          value={approvalRuns.length}
          tone="info"
        />
        <ApprovalMetricCard
          label="Pending"
          value={pendingRuns.length}
          tone="warning"
        />
        <ApprovalMetricCard
          label="Processing"
          value={processingRuns.length}
          tone="warning"
        />
        <ApprovalMetricCard
          label="Resolved"
          value={resolvedRuns.length}
          tone="success"
        />
      </section>

      <section className="sarvam-card rounded-[1.5rem] p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
            <Workflow className="h-4 w-4 text-[var(--accent)]" />
            Approval Queue
          </div>

          <div className="flex flex-wrap gap-2">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-black transition",
                  activeTab === tab.id
                    ? "border-[var(--border-strong)] bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
                    : "border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                )}
              >
                {tab.label} · {tab.count}
              </button>
            ))}
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading approvals...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && visibleRuns.length === 0 && (
        <section className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--success-soft)] text-[var(--success)]">
            <CheckCircle2 className="h-5 w-5" />
          </div>

          <h2 className="text-xl font-bold text-[var(--text-strong)]">
            No approvals in this view
          </h2>

          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
            Approval-gated actions will appear here when AIRA-X pauses before a
            risky operation.
          </p>
        </section>
      )}

      {!loading && !error && visibleRuns.length > 0 && (
        <section className="space-y-4">
          {visibleRuns
            .slice()
            .reverse()
            .map((run) => (
              <ApprovalCard
                key={run.run_id}
                run={run}
                actionRunId={actionRunId}
                actionType={actionType}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))}
        </section>
      )}
    </div>
  );
}
