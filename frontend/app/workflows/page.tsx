"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  Filter,
  GitBranch,
  History,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  Workflow,
  XCircle,
} from "lucide-react";
import {
  approveAiraX,
  deleteAiraXRun,
  deleteSafeAiraXRuns,
  getAiraXRuns,
  rejectAiraX,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ApprovalContext = {
  type?: string;
  preflight_scope?: string;
  tool_name?: string;
  tool_action?: string;
  pending_action?: string;

  commit_message?: string | null;
  branch?: string;
  changed_files?: string;
  diff_summary?: string;

  target_remote?: string;
  target_branch?: string;
  status_branch?: string;
  remote_info?: string;
  last_commit?: string;
  recent_commits?: string;
};

type ApprovalResolution = {
  status?: string;
  action?: string;
  requested_at?: string;
  completed_at?: string;
  final_status?: string;
  final_decision?: string;
  error?: string;
};

type CleanupAction = {
  reason: string;
  tool_name: string;
  tool_action: string;
  result?: {
    success?: boolean;
    command?: string;
    output?: string;
    error?: string;
  };
};

type WorkflowRunSummary = {
  run_id: string;
  user_goal: string;
  status: string;
  decision?: string | null;
  final_answer?: string | null;
  current_step?: number | null;
  retry_count: number;

  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;

  requires_approval: boolean;
  pending_action?: string;

  approval_context?: ApprovalContext;
  approval_context_type?: string;

  approval_in_progress?: boolean;
  approval_resolution?: ApprovalResolution;
  approval_resolution_status?: string;
  approval_resolution_action?: string;

  cleanup_actions?: CleanupAction[];
  cleanup_count?: number;
  has_cleanup?: boolean;

  approval_stale_recovered?: boolean;
  approval_recovery_count?: number;
  has_approval_recovery?: boolean;

  step_count: number;
  log_count: number;
};

type FilterTab =
  | "all"
  | "completed"
  | "approval"
  | "processing"
  | "failed"
  | "rejected"
  | "cleanup";

type SortMode =
  | "updated_desc"
  | "created_asc"
  | "completed_desc"
  | "status"
  | "goal"
  | "retries_high"
  | "logs_high";

type MetricTone = "blue" | "green" | "orange" | "red" | "purple" | "slate";

const APPROVAL_RESOLVED_STATUSES = new Set([
  "approved",
  "rejected",
  "approved_but_resume_failed",
  "stale_processing_recovered",
]);

function safeLower(value?: string | null) {
  return (value || "").toLowerCase();
}

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function getTimestampMs(value?: string | null) {
  if (!value) {
    return 0;
  }

  const timestamp = new Date(value).getTime();

  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function getMetricToneClass(tone: MetricTone) {
  if (tone === "green") {
    return "text-[var(--success)]";
  }

  if (tone === "orange") {
    return "text-[var(--warning)]";
  }

  if (tone === "red") {
    return "text-[var(--danger)]";
  }

  if (tone === "purple") {
    return "text-[var(--secondary)]";
  }

  if (tone === "slate") {
    return "text-[var(--text-strong)]";
  }

  return "text-[var(--accent)]";
}

function isApprovalProcessing(run?: WorkflowRunSummary | null) {
  return run?.approval_in_progress === true;
}

function isWaitingForApproval(run: WorkflowRunSummary) {
  return run.requires_approval || run.status === "requires_approval";
}

function isGitWritePreflight(run: WorkflowRunSummary) {
  return (
    run.approval_context_type === "git_write_preflight" ||
    run.approval_context?.type === "git_write_preflight"
  );
}

function isGitPushPreflight(run: WorkflowRunSummary) {
  return (
    run.approval_context_type === "git_push_preflight" ||
    run.approval_context?.type === "git_push_preflight"
  );
}

function hasAnyGitPreflight(run: WorkflowRunSummary) {
  return isGitWritePreflight(run) || isGitPushPreflight(run);
}

function hasStaleApprovalRecovery(run: WorkflowRunSummary) {
  return (
    run.approval_stale_recovered === true ||
    run.has_approval_recovery === true ||
    run.approval_resolution?.status === "stale_processing_recovered"
  );
}

function getApprovalResolution(
  run: WorkflowRunSummary
): ApprovalResolution | null {
  if (
    run.approval_resolution &&
    typeof run.approval_resolution === "object" &&
    Object.keys(run.approval_resolution).length > 0
  ) {
    return run.approval_resolution;
  }

  if (isApprovalProcessing(run)) {
    return {
      status: "processing",
      action: run.pending_action,
    };
  }

  return null;
}

function hasResolvedApproval(run: WorkflowRunSummary) {
  const status = run.approval_resolution?.status;

  return Boolean(status) && APPROVAL_RESOLVED_STATUSES.has(status || "");
}

function getStatusClass(status: string) {
  if (status === "completed") {
    return "status-success";
  }

  if (status === "failed" || status === "rejected") {
    return "status-danger";
  }

  if (status === "requires_approval" || status === "retrying") {
    return "status-warning";
  }

  return "status-info";
}

function getStatusIcon(status: string) {
  if (status === "completed") {
    return <CheckCircle2 className="h-3.5 w-3.5" />;
  }

  if (status === "failed" || status === "rejected") {
    return <XCircle className="h-3.5 w-3.5" />;
  }

  if (status === "requires_approval") {
    return <ShieldAlert className="h-3.5 w-3.5" />;
  }

  return <Clock className="h-3.5 w-3.5" />;
}

function getApprovalResolutionClass(status?: string) {
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

  if (status === "processing" || status === "in_progress") {
    return "status-warning";
  }

  return "status-info";
}

function getApprovalResolutionLabel(status?: string) {
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
    return "Stale recovered";
  }

  if (status === "processing" || status === "in_progress") {
    return "Processing";
  }

  return "Not resolved";
}

function getActionLabel(status: string) {
  if (status === "rejected") {
    return "Rejected action";
  }

  if (status === "requires_approval") {
    return "Pending action";
  }

  return "Action";
}

function getRunLastActivity(run: WorkflowRunSummary) {
  return run.updated_at || run.completed_at || run.created_at;
}

function getRunSearchText(run: WorkflowRunSummary) {
  return [
    run.user_goal,
    run.run_id,
    run.status,
    run.decision,
    run.final_answer,
    run.pending_action,
    run.approval_context?.branch,
    run.approval_context?.target_branch,
    run.approval_context?.target_remote,
    run.approval_context?.commit_message,
    run.created_at,
    run.updated_at,
    run.completed_at,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getFilteredRuns(
  runs: WorkflowRunSummary[],
  activeTab: FilterTab,
  searchQuery: string,
  preflightFilter: string
) {
  const normalizedSearchQuery = searchQuery.trim().toLowerCase();

  return runs.filter((run) => {
    const matchesTab =
      activeTab === "all" ||
      (activeTab === "completed" && run.status === "completed") ||
      (activeTab === "approval" && isWaitingForApproval(run)) ||
      (activeTab === "processing" && isApprovalProcessing(run)) ||
      (activeTab === "failed" && run.status === "failed") ||
      (activeTab === "rejected" && run.status === "rejected") ||
      (activeTab === "cleanup" && Boolean(run.has_cleanup));

    const matchesSearch =
      !normalizedSearchQuery ||
      getRunSearchText(run).includes(normalizedSearchQuery);

    const matchesPreflight =
      preflightFilter === "all" ||
      (preflightFilter === "any_git" && hasAnyGitPreflight(run)) ||
      (preflightFilter === "git_write" && isGitWritePreflight(run)) ||
      (preflightFilter === "git_push" && isGitPushPreflight(run)) ||
      (preflightFilter === "approval_resolved" && hasResolvedApproval(run)) ||
      (preflightFilter === "stale_recovery" && hasStaleApprovalRecovery(run));

    return matchesTab && matchesSearch && matchesPreflight;
  });
}

function sortRuns(runs: WorkflowRunSummary[], sortMode: SortMode) {
  return runs.slice().sort((firstRun, secondRun) => {
    if (sortMode === "created_asc") {
      return (
        getTimestampMs(firstRun.created_at) -
        getTimestampMs(secondRun.created_at)
      );
    }

    if (sortMode === "completed_desc") {
      return (
        getTimestampMs(secondRun.completed_at) -
        getTimestampMs(firstRun.completed_at)
      );
    }

    if (sortMode === "status") {
      return firstRun.status.localeCompare(secondRun.status);
    }

    if (sortMode === "goal") {
      return firstRun.user_goal.localeCompare(secondRun.user_goal);
    }

    if (sortMode === "retries_high") {
      return secondRun.retry_count - firstRun.retry_count;
    }

    if (sortMode === "logs_high") {
      return secondRun.log_count - firstRun.log_count;
    }

    return (
      getTimestampMs(getRunLastActivity(secondRun)) -
      getTimestampMs(getRunLastActivity(firstRun))
    );
  });
}

function MetricCard({
  label,
  value,
  tone = "blue",
  icon,
  description,
}: {
  label: string;
  value: number;
  tone?: MetricTone;
  icon?: ReactNode;
  description?: string;
}) {
  return (
    <div className="sarvam-card rounded-[1.35rem] p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
          {label}
        </p>

        {icon && (
          <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] text-[var(--accent)]">
            {icon}
          </div>
        )}
      </div>

      <h2 className={cn("text-3xl font-black", getMetricToneClass(tone))}>
        {formatNumber(value)}
      </h2>

      {description && (
        <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
          {description}
        </p>
      )}
    </div>
  );
}

function FilterTabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-xs font-black transition",
        active
          ? "border-[var(--border-strong)] bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]"
          : "border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
      )}
    >
      {label} · {formatNumber(count)}
    </button>
  );
}

function RunBadge({
  children,
  className,
}: {
  children: ReactNode;
  className: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-black",
        className
      )}
    >
      {children}
    </span>
  );
}

function PreflightPreview({ run }: { run: WorkflowRunSummary }) {
  const context = run.approval_context || {};
  const gitWritePreflight = isGitWritePreflight(run);
  const gitPushPreflight = isGitPushPreflight(run);

  if (!gitWritePreflight && !gitPushPreflight) {
    return null;
  }

  return (
    <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-black text-[var(--text-strong)]">
        {gitPushPreflight ? (
          <UploadCloud className="h-4 w-4 text-[var(--danger)]" />
        ) : (
          <GitBranch className="h-4 w-4 text-[var(--warning)]" />
        )}
        {gitPushPreflight ? "Git Push Preflight" : "Git Write Preflight"}
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

          <p className="mt-1 break-words text-sm font-semibold text-[var(--text)]">
            {gitPushPreflight
              ? `${context.target_remote || "origin"} / ${
                  context.target_branch || context.branch || "unknown"
                }`
              : context.commit_message || context.pending_action || "Git write"}
          </p>
        </div>
      </div>

      {gitPushPreflight && context.last_commit && (
        <div className="mt-3">
          <p className="mb-1 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Latest Local Commit
          </p>

          <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded-xl p-3 text-[11px] leading-5">
            {context.last_commit}
          </pre>
        </div>
      )}
    </div>
  );
}

function ApprovalResolutionPanel({ run }: { run: WorkflowRunSummary }) {
  const approvalResolution = getApprovalResolution(run);

  if (!approvalResolution) {
    return null;
  }

  const status = approvalResolution.status;

  return (
    <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <RunBadge className={getApprovalResolutionClass(status)}>
          <ShieldAlert className="h-3.5 w-3.5" />
          Approval: {getApprovalResolutionLabel(status)}
        </RunBadge>
      </div>

      <div className="grid gap-3 text-xs md:grid-cols-2">
        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Action:</strong>{" "}
          {approvalResolution.action || run.pending_action || "Not recorded"}
        </p>

        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Completed:</strong>{" "}
          {formatDateTime(approvalResolution.completed_at)}
        </p>

        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Final Status:</strong>{" "}
          {approvalResolution.final_status || run.status || "Not recorded"}
        </p>

        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Final Decision:</strong>{" "}
          {approvalResolution.final_decision || run.decision || "Not recorded"}
        </p>
      </div>

      {approvalResolution.error && (
        <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-3 text-xs leading-5 text-[var(--danger)]">
          <strong>Error:</strong> {approvalResolution.error}
        </div>
      )}
    </div>
  );
}

function CleanupPanel({ run }: { run: WorkflowRunSummary }) {
  if (!run.has_cleanup) {
    return null;
  }

  const firstCleanup = run.cleanup_actions?.[0];

  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-black text-[var(--success)]">
        <CheckCircle2 className="h-4 w-4" />
        Cleanup Performed
      </div>

      <div className="grid gap-3 text-xs md:grid-cols-3">
        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Count:</strong>{" "}
          {run.cleanup_count || 0}
        </p>

        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Action:</strong>{" "}
          {firstCleanup
            ? `${firstCleanup.tool_name}:${firstCleanup.tool_action}`
            : "Not recorded"}
        </p>

        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-[var(--text-muted)]">
          <strong className="text-[var(--text-strong)]">Status:</strong>{" "}
          {firstCleanup?.result?.success ? "successful" : "not recorded"}
        </p>
      </div>
    </div>
  );
}

function ApprovalActionPanel({
  run,
  actionRunId,
  actionType,
  onApprove,
  onReject,
}: {
  run: WorkflowRunSummary;
  actionRunId: string | null;
  actionType: "approve" | "reject" | null;
  onApprove: (runId: string) => Promise<void>;
  onReject: (runId: string) => Promise<void>;
}) {
  const waitingForApproval = isWaitingForApproval(run);
  const approvalProcessing = isApprovalProcessing(run);

  if (!waitingForApproval) {
    return null;
  }

  const actionInProgress = actionRunId === run.run_id;
  const actionButtonsDisabled = Boolean(actionRunId) || approvalProcessing;

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <p className="flex items-center gap-2 text-sm font-black text-[var(--warning)]">
          {approvalProcessing ? (
            <Clock className="h-4 w-4" />
          ) : (
            <ShieldCheck className="h-4 w-4" />
          )}
          {approvalProcessing ? "Approval is being processed" : "Approval Required"}
        </p>

        <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
          {approvalProcessing
            ? "AIRA-X is already processing this action. Controls are disabled to prevent duplicate execution."
            : "Approve to continue this workflow, or reject to stop it safely."}
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => onApprove(run.run_id)}
          disabled={actionButtonsDisabled}
          className="rounded-xl bg-[var(--warning)] px-4 py-2.5 text-xs font-black text-white shadow-[var(--shadow-soft)] transition disabled:cursor-not-allowed disabled:opacity-60"
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
          className="inline-flex items-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--danger-soft)] disabled:cursor-not-allowed disabled:opacity-60"
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
  );
}

function WorkflowRunCard({
  run,
  actionRunId,
  actionType,
  deleteRunId,
  onApprove,
  onReject,
  onDelete,
}: {
  run: WorkflowRunSummary;
  actionRunId: string | null;
  actionType: "approve" | "reject" | null;
  deleteRunId: string | null;
  onApprove: (runId: string) => Promise<void>;
  onReject: (runId: string) => Promise<void>;
  onDelete: (run: WorkflowRunSummary) => Promise<void>;
}) {
  const gitWritePreflight = isGitWritePreflight(run);
  const gitPushPreflight = isGitPushPreflight(run);
  const approvalProcessing = isApprovalProcessing(run);
  const staleApprovalRecovery = hasStaleApprovalRecovery(run);
  const deleteInProgress = deleteRunId === run.run_id;
  const deleteDisabled =
    Boolean(deleteRunId) || Boolean(actionRunId) || approvalProcessing;

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <RunBadge className={getStatusClass(run.status)}>
              {getStatusIcon(run.status)}
              {run.status}
            </RunBadge>

            {approvalProcessing && (
              <RunBadge className="status-warning">
                <Clock className="h-3.5 w-3.5" />
                Approval Processing
              </RunBadge>
            )}

            {staleApprovalRecovery && (
              <RunBadge className="status-danger">
                <XCircle className="h-3.5 w-3.5" />
                Stale Recovery
              </RunBadge>
            )}

            {gitWritePreflight && (
              <RunBadge className="status-warning">
                <GitBranch className="h-3.5 w-3.5" />
                Git Write
              </RunBadge>
            )}

            {gitPushPreflight && (
              <RunBadge className="status-danger">
                <UploadCloud className="h-3.5 w-3.5" />
                Git Push
              </RunBadge>
            )}

            {run.has_cleanup && (
              <RunBadge className="status-success">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Cleanup
              </RunBadge>
            )}
          </div>

          <Link href={`/workflows/${run.run_id}`} className="group block">
            <h3 className="line-clamp-1 text-base font-black text-[var(--text-strong)] group-hover:text-[var(--accent)]">
              {run.user_goal || "Untitled workflow"}
            </h3>

            <p className="mt-1 break-all font-mono text-[11px] text-[var(--text-subtle)]">
              {run.run_id}
            </p>
          </Link>

          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Decision
              </p>

              <p className="mt-1 truncate text-sm font-semibold text-[var(--text-strong)]">
                {run.decision || "Not recorded"}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Steps
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {run.step_count}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Logs
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {run.log_count}
              </p>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
              <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                Retries
              </p>

              <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
                {run.retry_count}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 text-xs md:grid-cols-3">
            <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
              <strong className="text-[var(--text-strong)]">Created:</strong>{" "}
              {formatDateTime(run.created_at)}
            </p>

            <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
              <strong className="text-[var(--text-strong)]">Updated:</strong>{" "}
              {formatDateTime(run.updated_at)}
            </p>

            <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[var(--text-muted)]">
              <strong className="text-[var(--text-strong)]">Completed:</strong>{" "}
              {formatDateTime(run.completed_at)}
            </p>
          </div>

          <p className="mt-4 line-clamp-2 text-sm leading-6 text-[var(--text-muted)]">
            <strong className="text-[var(--text-strong)]">Final Answer:</strong>{" "}
            {run.final_answer || "No final answer recorded yet."}
          </p>

          {run.pending_action && (
            <p className="mt-2 line-clamp-2 text-sm leading-6 text-[var(--text-muted)]">
              <strong className="text-[var(--text-strong)]">
                {getActionLabel(run.status)}:
              </strong>{" "}
              {run.pending_action}
            </p>
          )}

          <ApprovalResolutionPanel run={run} />
          <PreflightPreview run={run} />
          <CleanupPanel run={run} />
          <ApprovalActionPanel
            run={run}
            actionRunId={actionRunId}
            actionType={actionType}
            onApprove={onApprove}
            onReject={onReject}
          />
        </div>

        <div className="flex shrink-0 flex-col gap-3 xl:w-48">
          <Link
            href={`/workflows/${run.run_id}`}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            Open Details
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>

          <button
            type="button"
            onClick={() => onDelete(run)}
            disabled={deleteDisabled}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-4 py-2.5 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {deleteInProgress ? (
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            {deleteInProgress ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </article>
  );
}

export default function WorkflowsPage() {
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [actionRunId, setActionRunId] = useState<string | null>(null);
  const [actionType, setActionType] = useState<"approve" | "reject" | null>(
    null
  );
  const [deleteRunId, setDeleteRunId] = useState<string | null>(null);
  const [safeCleanupLoading, setSafeCleanupLoading] = useState(false);
  const [safeCleanupSummary, setSafeCleanupSummary] = useState("");
  const [polling, setPolling] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [preflightFilter, setPreflightFilter] = useState("all");
  const [sortMode, setSortMode] = useState<SortMode>("updated_desc");
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
        err instanceof Error ? err.message : "Failed to load workflow runs.";

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

  async function handleDelete(run: WorkflowRunSummary) {
    if (isApprovalProcessing(run)) {
      return;
    }

    const confirmed = window.confirm(
      `Delete this workflow run from history?\\n\\n${run.user_goal}\\n\\nThis only removes the saved run record.`
    );

    if (!confirmed) {
      return;
    }

    try {
      setDeleteRunId(run.run_id);
      setError("");

      await deleteAiraXRun(run.run_id);
      await loadRuns({ showLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to delete workflow run.";

      setError(message);
      await loadRuns({ showLoading: false });
    } finally {
      setDeleteRunId(null);
    }
  }

  async function handleSafeCleanup() {
    const confirmed = window.confirm(
      "Clean workflow history safely?\\n\\nThis deletes only completed, failed, and rejected workflow runs. Active approval, retrying, executing, and approval-processing runs are skipped."
    );

    if (!confirmed) {
      return;
    }

    try {
      setSafeCleanupLoading(true);
      setSafeCleanupSummary("");
      setError("");

      const response = await deleteSafeAiraXRuns();

      setSafeCleanupSummary(
        `Safe cleanup complete: deleted ${response.deleted_count} run${
          response.deleted_count === 1 ? "" : "s"
        }, skipped ${response.skipped_count}.`
      );

      await loadRuns({ showLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to clean workflow history.";

      setError(message);
      await loadRuns({ showLoading: false });
    } finally {
      setSafeCleanupLoading(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const completedCount = runs.filter((run) => run.status === "completed").length;
  const failedCount = runs.filter((run) => run.status === "failed").length;
  const rejectedCount = runs.filter((run) => run.status === "rejected").length;
  const approvalRunCount = runs.filter((run) => isWaitingForApproval(run)).length;
  const approvalProcessingCount = runs.filter((run) =>
    isApprovalProcessing(run)
  ).length;
  const cleanupRunCount = runs.filter((run) => run.has_cleanup).length;
  const gitPreflightCount = runs.filter((run) => hasAnyGitPreflight(run)).length;
  const staleRecoveryCount = runs.filter((run) =>
    hasStaleApprovalRecovery(run)
  ).length;

  const filteredRuns = useMemo(
    () => getFilteredRuns(runs, activeTab, searchQuery, preflightFilter),
    [runs, activeTab, searchQuery, preflightFilter]
  );

  const sortedFilteredRuns = useMemo(
    () => sortRuns(filteredRuns, sortMode),
    [filteredRuns, sortMode]
  );

  const tabs = [
    { id: "all" as const, label: "All", count: runs.length },
    { id: "completed" as const, label: "Completed", count: completedCount },
    { id: "approval" as const, label: "Needs Approval", count: approvalRunCount },
    {
      id: "processing" as const,
      label: "Processing",
      count: approvalProcessingCount,
    },
    { id: "failed" as const, label: "Failed", count: failedCount },
    { id: "rejected" as const, label: "Rejected", count: rejectedCount },
    { id: "cleanup" as const, label: "Cleanup", count: cleanupRunCount },
  ];

  useEffect(() => {
    if (approvalProcessingCount === 0) {
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
  }, [approvalProcessingCount, loadRuns]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_23rem]">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              <Workflow className="h-3.5 w-3.5" />
              AIRA-X Workflow History
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              Workflow Runs
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              Review execution traces, approval states, decisions, Git
              preflights, cleanup actions, stale recovery events, and final
              outcomes for every autonomous run.
            </p>

            <div className="mt-5 flex flex-wrap gap-3">
              <Link
                href="/chat"
                className="inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-4 py-2.5 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
              >
                <Workflow className="h-3.5 w-3.5" />
                Open Execute Panel
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>

              <Link
                href="/approvals"
                className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                Review Approvals
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>

            {polling && (
              <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-3 py-1.5 text-xs font-black text-[var(--accent)]">
                <Activity className="h-3.5 w-3.5" />
                Auto-refreshing processing approvals
              </div>
            )}

            {safeCleanupSummary && (
              <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-3 text-sm font-semibold text-[var(--success)]">
                {safeCleanupSummary}
              </div>
            )}
          </div>

          <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--danger-soft)] text-[var(--danger)]">
                <Trash2 className="h-4 w-4" />
              </div>

              <div>
                <h2 className="text-sm font-black text-[var(--text-strong)]">
                  History Maintenance
                </h2>

                <p className="text-xs leading-5 text-[var(--text-muted)]">
                  Remove completed, failed, and rejected runs safely.
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleSafeCleanup}
              disabled={
                safeCleanupLoading || Boolean(actionRunId) || Boolean(deleteRunId)
              }
              className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-4 py-3 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {safeCleanupLoading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {safeCleanupLoading ? "Cleaning history..." : "Safe Cleanup"}
            </button>

            <p className="mt-3 text-xs leading-5 text-[var(--text-subtle)]">
              Active, approval-processing, retrying, and executing workflows are
              skipped automatically.
            </p>
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading workflow runs...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Total Runs"
              value={runCount}
              tone="blue"
              icon={<History className="h-4 w-4" />}
            />

            <MetricCard
              label="Completed"
              value={completedCount}
              tone="green"
              icon={<CheckCircle2 className="h-4 w-4" />}
            />

            <MetricCard
              label="Needs Approval"
              value={approvalRunCount}
              tone="orange"
              icon={<ShieldAlert className="h-4 w-4" />}
            />

            <MetricCard
              label="Failed / Rejected"
              value={failedCount + rejectedCount}
              tone="red"
              icon={<XCircle className="h-4 w-4" />}
            />
          </section>

          <section className="grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Git Preflights"
              value={gitPreflightCount}
              tone="purple"
              icon={<GitBranch className="h-4 w-4" />}
              description="Git write and push approval previews."
            />

            <MetricCard
              label="Cleanup Runs"
              value={cleanupRunCount}
              tone="green"
              icon={<CheckCircle2 className="h-4 w-4" />}
              description="Runs with cleanup actions recorded."
            />

            <MetricCard
              label="Stale Recoveries"
              value={staleRecoveryCount}
              tone="red"
              icon={<ShieldAlert className="h-4 w-4" />}
              description="Approval deadlocks safely stopped."
            />
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                  <Filter className="h-4 w-4" />
                </div>

                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Workflow Explorer
                  </h2>

                  <p className="text-sm text-[var(--text-muted)]">
                    Showing {formatNumber(filteredRuns.length)} of{" "}
                    {formatNumber(runs.length)} saved runs.
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => loadRuns({ showLoading: false })}
                className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </button>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
              {tabs.map((tab) => (
                <FilterTabButton
                  key={tab.id}
                  label={tab.label}
                  count={tab.count}
                  active={activeTab === tab.id}
                  onClick={() => setActiveTab(tab.id)}
                />
              ))}
            </div>

            <div className="grid gap-3 lg:grid-cols-[1fr_220px_220px]">
              <label className="relative block">
                <span className="sr-only">Search workflows</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

                <input
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Search goal, run ID, decision, action..."
                  className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm text-[var(--text-strong)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
                />
              </label>

              <label className="relative block">
                <span className="sr-only">Preflight filter</span>
                <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

                <select
                  value={preflightFilter}
                  onChange={(event) => setPreflightFilter(event.target.value)}
                  className="w-full appearance-none rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm font-semibold text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
                >
                  <option value="all">All run types</option>
                  <option value="any_git">Any Git preflight</option>
                  <option value="git_write">Git write preflight</option>
                  <option value="git_push">Git push preflight</option>
                  <option value="approval_resolved">Approval resolved</option>
                  <option value="stale_recovery">Stale recovery</option>
                </select>
              </label>

              <label className="relative block">
                <span className="sr-only">Sort workflows</span>
                <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

                <select
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value as SortMode)}
                  className="w-full appearance-none rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm font-semibold text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
                >
                  <option value="updated_desc">Newest activity</option>
                  <option value="created_asc">Oldest created</option>
                  <option value="completed_desc">Recently completed</option>
                  <option value="status">Status A-Z</option>
                  <option value="goal">Goal A-Z</option>
                  <option value="retries_high">Retries high-low</option>
                  <option value="logs_high">Logs high-low</option>
                </select>
              </label>
            </div>

            {(searchQuery ||
              activeTab !== "all" ||
              preflightFilter !== "all" ||
              sortMode !== "updated_desc") && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery("");
                  setActiveTab("all");
                  setPreflightFilter("all");
                  setSortMode("updated_desc");
                }}
                className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                Clear Filters
              </button>
            )}
          </section>

          <section className="space-y-4">
            {runs.length === 0 ? (
              <div className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                  <Workflow className="h-5 w-5" />
                </div>

                <h2 className="text-xl font-black text-[var(--text-strong)]">
                  No workflow runs yet
                </h2>

                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                  Run AIRA-X from the Execute page and every traceable workflow
                  will appear here.
                </p>

                <Link
                  href="/chat"
                  className="mt-5 inline-flex items-center gap-2 rounded-2xl bg-[var(--accent)] px-5 py-3 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
                >
                  <Workflow className="h-4 w-4" />
                  Open Execute Panel
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            ) : sortedFilteredRuns.length === 0 ? (
              <div className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                  <Search className="h-5 w-5" />
                </div>

                <h2 className="text-xl font-black text-[var(--text-strong)]">
                  No matching runs
                </h2>

                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                  Try clearing filters or searching a different goal, run ID,
                  decision, status, or pending action.
                </p>
              </div>
            ) : (
              sortedFilteredRuns.map((run) => (
                <WorkflowRunCard
                  key={run.run_id}
                  run={run}
                  actionRunId={actionRunId}
                  actionType={actionType}
                  deleteRunId={deleteRunId}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  onDelete={handleDelete}
                />
              ))
            )}
          </section>
        </>
      )}
    </div>
  );
}
