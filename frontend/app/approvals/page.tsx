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
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
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

type ApprovalTab =
  | "pending"
  | "processing"
  | "resolved"
  | "rejected"
  | "stale"
  | "all";

type PreflightFilter = "all" | "git_write" | "git_push" | "git_any";

type SortMode =
  | "newest"
  | "oldest"
  | "status"
  | "goal"
  | "completed_desc";

type MetricTone = "info" | "warning" | "success" | "danger" | "purple";

const RESOLVED_APPROVAL_STATUSES = new Set([
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

function getLastActivity(run: AiraXWorkflowRun) {
  return (
    run.updated_at ||
    run.approval_resolution?.completed_at ||
    run.approval_resolution?.requested_at ||
    run.completed_at ||
    run.created_at
  );
}

function isApprovalProcessing(run?: AiraXWorkflowRun | null) {
  return (
    run?.approval_in_progress === true ||
    run?.memory?.approval_in_progress === true
  );
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

function hasRejectedApproval(run: AiraXWorkflowRun) {
  return (
    run.approval_resolution?.status === "rejected" ||
    (run.status === "rejected" && hasApprovalResolution(run))
  );
}

function hasStaleApprovalRecovery(run: AiraXWorkflowRun) {
  return (
    run.approval_stale_recovered === true ||
    run.has_approval_recovery === true ||
    run.approval_resolution?.status === "stale_processing_recovered"
  );
}

function getApprovalStatus(run: AiraXWorkflowRun) {
  if (isApprovalProcessing(run)) {
    return "processing";
  }

  const resolutionStatus = run.approval_resolution?.status;

  if (
    resolutionStatus &&
    RESOLVED_APPROVAL_STATUSES.has(resolutionStatus)
  ) {
    return resolutionStatus;
  }

  if (isWaitingForApproval(run)) {
    return "pending";
  }

  if (resolutionStatus) {
    return resolutionStatus;
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

function getApprovalIcon(status: string) {
  if (status === "approved") {
    return <CheckCircle2 className="h-3.5 w-3.5" />;
  }

  if (
    status === "rejected" ||
    status === "approved_but_resume_failed" ||
    status === "stale_processing_recovered"
  ) {
    return <XCircle className="h-3.5 w-3.5" />;
  }

  if (status === "processing" || status === "in_progress") {
    return <Clock className="h-3.5 w-3.5" />;
  }

  return <ShieldAlert className="h-3.5 w-3.5" />;
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

function hasAnyGitPreflight(run: AiraXWorkflowRun) {
  return isGitWritePreflight(run) || isGitPushPreflight(run);
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

function getSearchText(run: AiraXWorkflowRun) {
  return [
    run.user_goal,
    run.run_id,
    run.status,
    run.decision,
    run.final_answer,
    getRunAction(run),
    run.approval_resolution?.status,
    run.approval_context?.branch,
    run.approval_context?.target_branch,
    run.approval_context?.target_remote,
    run.approval_context?.commit_message,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getFilteredApprovalRuns(
  approvalRuns: AiraXWorkflowRun[],
  activeTab: ApprovalTab,
  searchQuery: string,
  preflightFilter: PreflightFilter
) {
  const normalizedSearch = searchQuery.trim().toLowerCase();

  return approvalRuns.filter((run) => {
    const matchesTab =
      activeTab === "all" ||
      (activeTab === "pending" &&
        isWaitingForApproval(run) &&
        !isApprovalProcessing(run) &&
        !hasResolvedApproval(run) &&
        !hasRejectedApproval(run) &&
        !hasStaleApprovalRecovery(run)) ||
      (activeTab === "processing" && isApprovalProcessing(run)) ||
      (activeTab === "resolved" && hasResolvedApproval(run)) ||
      (activeTab === "rejected" && hasRejectedApproval(run)) ||
      (activeTab === "stale" && hasStaleApprovalRecovery(run));

    const matchesSearch =
      !normalizedSearch || getSearchText(run).includes(normalizedSearch);

    const matchesPreflight =
      preflightFilter === "all" ||
      (preflightFilter === "git_any" && hasAnyGitPreflight(run)) ||
      (preflightFilter === "git_write" && isGitWritePreflight(run)) ||
      (preflightFilter === "git_push" && isGitPushPreflight(run));

    return matchesTab && matchesSearch && matchesPreflight;
  });
}

function sortApprovalRuns(runs: AiraXWorkflowRun[], sortMode: SortMode) {
  return runs.slice().sort((firstRun, secondRun) => {
    if (sortMode === "oldest") {
      return getTimestampMs(getLastActivity(firstRun)) - getTimestampMs(getLastActivity(secondRun));
    }

    if (sortMode === "status") {
      return getApprovalStatus(firstRun).localeCompare(getApprovalStatus(secondRun));
    }

    if (sortMode === "goal") {
      return safeLower(firstRun.user_goal).localeCompare(safeLower(secondRun.user_goal));
    }

    if (sortMode === "completed_desc") {
      return (
        getTimestampMs(secondRun.approval_resolution?.completed_at) -
        getTimestampMs(firstRun.approval_resolution?.completed_at)
      );
    }

    return getTimestampMs(getLastActivity(secondRun)) - getTimestampMs(getLastActivity(firstRun));
  });
}

function getMetricToneClass(tone: MetricTone) {
  if (tone === "warning") {
    return "text-[var(--warning)]";
  }

  if (tone === "success") {
    return "text-[var(--success)]";
  }

  if (tone === "danger") {
    return "text-[var(--danger)]";
  }

  if (tone === "purple") {
    return "text-[var(--secondary)]";
  }

  return "text-[var(--accent)]";
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

function FieldCard({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
      <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
        {label}
      </p>

      <div
        className={cn(
          "mt-1 break-words text-sm font-semibold text-[var(--text-strong)]",
          mono && "font-mono text-xs"
        )}
      >
        {value}
      </div>
    </div>
  );
}

function ApprovalMetricCard({
  label,
  value,
  tone,
  icon,
  description,
}: {
  label: string;
  value: number;
  tone: MetricTone;
  icon: ReactNode;
  description?: string;
}) {
  return (
    <div className="sarvam-card rounded-[1.35rem] p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
          {label}
        </p>

        <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] text-[var(--accent)]">
          {icon}
        </div>
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

function TabButton({
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

function PreflightPreview({ run }: { run: AiraXWorkflowRun }) {
  const gitPushPreflight = isGitPushPreflight(run);
  const gitWritePreflight = isGitWritePreflight(run);
  const context = run.approval_context || {};

  if (!gitPushPreflight && !gitWritePreflight) {
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
        <FieldCard label="Current Branch" value={context.branch || "Unknown branch"} />
        <FieldCard
          label={gitPushPreflight ? "Remote Target" : "Commit / Action"}
          value={
            gitPushPreflight
              ? `${context.target_remote || "origin"} / ${
                  context.target_branch || context.branch || "unknown"
                }`
              : context.commit_message || context.pending_action || "Git write action"
          }
        />
      </div>

      {gitPushPreflight && context.last_commit && (
        <div className="mt-3">
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Latest Local Commit
          </p>

          <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded-2xl p-3 text-[11px] leading-5">
            {context.last_commit}
          </pre>
        </div>
      )}
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
  const resolution = run.approval_resolution;
  const showControls =
    waitingForApproval &&
    !hasResolvedApproval(run) &&
    !hasRejectedApproval(run) &&
    !hasStaleApprovalRecovery(run);

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <RunBadge className={getApprovalBadgeClass(approvalStatus)}>
              {getApprovalIcon(approvalStatus)}
              {getApprovalLabel(approvalStatus)}
            </RunBadge>

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

            {hasStaleApprovalRecovery(run) && (
              <RunBadge className="status-danger">
                <XCircle className="h-3.5 w-3.5" />
                Stale Recovery
              </RunBadge>
            )}

            <RunBadge className="border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)]">
              Workflow: {run.status}
            </RunBadge>
          </div>

          <Link href={`/workflows/${run.run_id}`} className="group block">
            <h2 className="line-clamp-1 text-base font-black text-[var(--text-strong)] group-hover:text-[var(--accent)]">
              {run.user_goal || "Untitled workflow"}
            </h2>

            <p className="mt-1 break-all font-mono text-[11px] text-[var(--text-subtle)]">
              {run.run_id}
            </p>
          </Link>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <FieldCard label="Approval Action" value={getRunAction(run)} />
            <FieldCard label="Decision" value={run.decision || "Not recorded"} />
            <FieldCard
              label="Requested"
              value={formatDateTime(resolution?.requested_at)}
            />
            <FieldCard
              label="Completed"
              value={formatDateTime(resolution?.completed_at)}
            />
          </div>

          <PreflightPreview run={run} />

          {resolution?.error && (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-3 text-sm leading-6 text-[var(--danger)]">
              <strong>Error:</strong> {resolution.error}
            </div>
          )}

          {run.final_answer && (
            <p className="mt-4 line-clamp-2 text-sm leading-6 text-[var(--text-muted)]">
              <strong className="text-[var(--text-strong)]">Final answer:</strong>{" "}
              {run.final_answer}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col gap-3 xl:w-80">
          <Link
            href={`/workflows/${run.run_id}`}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            Open Workflow
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>

          {showControls && (
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-4">
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
      </div>
    </article>
  );
}

export default function ApprovalsPage() {
  const [runs, setRuns] = useState<AiraXWorkflowRun[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [activeTab, setActiveTab] = useState<ApprovalTab>("pending");
  const [preflightFilter, setPreflightFilter] = useState<PreflightFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("newest");
  const [searchQuery, setSearchQuery] = useState("");
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

    if (actionRunId || isApprovalProcessing(currentRun)) {
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

    if (actionRunId || isApprovalProcessing(currentRun)) {
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
          hasResolvedApproval(run) ||
          hasRejectedApproval(run) ||
          hasStaleApprovalRecovery(run)
      ),
    [runs]
  );

  const pendingRuns = useMemo(
    () =>
      approvalRuns.filter(
        (run) =>
          isWaitingForApproval(run) &&
          !isApprovalProcessing(run) &&
          !hasResolvedApproval(run) &&
          !hasRejectedApproval(run) &&
          !hasStaleApprovalRecovery(run)
      ),
    [approvalRuns]
  );

  const processingRuns = useMemo(
    () => approvalRuns.filter((run) => isApprovalProcessing(run)),
    [approvalRuns]
  );

  const resolvedRuns = useMemo(
    () => approvalRuns.filter((run) => hasResolvedApproval(run)),
    [approvalRuns]
  );

  const rejectedRuns = useMemo(
    () => approvalRuns.filter((run) => hasRejectedApproval(run)),
    [approvalRuns]
  );

  const staleRecoveryRuns = useMemo(
    () => approvalRuns.filter((run) => hasStaleApprovalRecovery(run)),
    [approvalRuns]
  );

  const visibleRuns = useMemo(
    () =>
      sortApprovalRuns(
        getFilteredApprovalRuns(
          approvalRuns,
          activeTab,
          searchQuery,
          preflightFilter
        ),
        sortMode
      ),
    [approvalRuns, activeTab, searchQuery, preflightFilter, sortMode]
  );

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
    { id: "rejected", label: "Rejected", count: rejectedRuns.length },
    { id: "stale", label: "Stale Recovery", count: staleRecoveryRuns.length },
    { id: "all", label: "All", count: approvalRuns.length },
  ];

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              <ShieldCheck className="h-3.5 w-3.5" />
              AIRA-X Safety
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              Approvals
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              Review risky actions requested by Assistant that can modify your
              environment, write Git history, or push to a remote repository.
              Pending, processing, and resolved approvals stay separated for
              clear human-in-the-loop control.
            </p>

            <div className="mt-5 flex flex-wrap gap-3">
              <Link
                href="/chat"
                className="inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-4 py-2.5 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
              >
                <Workflow className="h-3.5 w-3.5" />
                Open Assistant
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>

              <Link
                href="/workflows"
                className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                <GitBranch className="h-3.5 w-3.5" />
                View Workflow Runs
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>

          {polling && (
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-3 py-1.5 text-xs font-black text-[var(--accent)]">
              <Activity className="h-3.5 w-3.5" />
              Auto-refreshing
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <ApprovalMetricCard
          label="Approval Runs"
          value={approvalRuns.length}
          tone="info"
          icon={<ShieldAlert className="h-4 w-4" />}
          description={`${formatNumber(runCount)} total workflow runs`}
        />
        <ApprovalMetricCard
          label="Pending"
          value={pendingRuns.length}
          tone="warning"
          icon={<Clock className="h-4 w-4" />}
          description="Waiting for user action"
        />
        <ApprovalMetricCard
          label="Processing"
          value={processingRuns.length}
          tone="warning"
          icon={<Activity className="h-4 w-4" />}
          description="Approval action in progress"
        />
        <ApprovalMetricCard
          label="Resolved"
          value={resolvedRuns.length}
          tone="success"
          icon={<CheckCircle2 className="h-4 w-4" />}
          description="Completed approval decisions"
        />
        <ApprovalMetricCard
          label="Rejected / Stale"
          value={rejectedRuns.length + staleRecoveryRuns.length}
          tone="danger"
          icon={<XCircle className="h-4 w-4" />}
          description="Stopped or recovered safely"
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
                Approval Queue
              </h2>

              <p className="text-sm text-[var(--text-muted)]">
                Showing {formatNumber(visibleRuns.length)} of{" "}
                {formatNumber(approvalRuns.length)} approval-related runs.
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
            <TabButton
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
            <span className="sr-only">Search approvals</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search goal, run ID, action, branch..."
              className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm text-[var(--text-strong)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
            />
          </label>

          <label className="relative block">
            <span className="sr-only">Preflight filter</span>
            <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

            <select
              value={preflightFilter}
              onChange={(event) =>
                setPreflightFilter(event.target.value as PreflightFilter)
              }
              className="w-full appearance-none rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm font-semibold text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
            >
              <option value="all">All approval types</option>
              <option value="git_any">Any Git preflight</option>
              <option value="git_write">Git write</option>
              <option value="git_push">Git push</option>
            </select>
          </label>

          <label className="relative block">
            <span className="sr-only">Sort approvals</span>
            <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

            <select
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value as SortMode)}
              className="w-full appearance-none rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm font-semibold text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
            >
              <option value="newest">Newest activity</option>
              <option value="oldest">Oldest activity</option>
              <option value="completed_desc">Recently completed</option>
              <option value="status">Approval status</option>
              <option value="goal">Goal A-Z</option>
            </select>
          </label>
        </div>

        {(searchQuery ||
          activeTab !== "pending" ||
          preflightFilter !== "all" ||
          sortMode !== "newest") && (
          <button
            type="button"
            onClick={() => {
              setSearchQuery("");
              setActiveTab("pending");
              setPreflightFilter("all");
              setSortMode("newest");
            }}
            className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            Clear Filters
          </button>
        )}
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

          <h2 className="text-xl font-black text-[var(--text-strong)]">
            No approvals in this view
          </h2>

          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
            Pending approvals, processing approvals, resolved decisions,
            rejected actions, and stale approval recoveries will appear here
            when matching this view.
          </p>

          <div className="mt-5 flex flex-wrap justify-center gap-3">
            <Link
              href="/chat"
              className="inline-flex items-center gap-2 rounded-2xl bg-[var(--accent)] px-5 py-3 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
            >
              <Workflow className="h-4 w-4" />
              Open Assistant
              <ArrowRight className="h-4 w-4" />
            </Link>

            <Link
              href="/workflows"
              className="inline-flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-black text-[var(--text-muted)] shadow-[var(--shadow-soft)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
            >
              <GitBranch className="h-4 w-4" />
              View Workflows
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      )}

      {!loading && !error && visibleRuns.length > 0 && (
        <section className="space-y-4">
          {visibleRuns.map((run) => (
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
