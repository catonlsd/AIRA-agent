"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock,
  GitBranch,
  GitCommit,
  History,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  Workflow,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  deleteSafeAiraXRuns,
  getAiraXOverview,
  type AiraXOverviewResponse,
  type AiraXWorkflowRun,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type MetricTone = "blue" | "green" | "orange" | "red" | "purple" | "slate";

function formatNumber(value?: number | null) {
  return typeof value === "number" ? value.toLocaleString() : "0";
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

function getStatusClass(status?: string) {
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

function getStatusIcon(status?: string) {
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

function MetricCard({
  label,
  value,
  icon,
  tone = "blue",
  description,
}: {
  label: string;
  value: number | undefined;
  icon?: React.ReactNode;
  tone?: MetricTone;
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

      <h3 className={cn("text-3xl font-black", getMetricToneClass(tone))}>
        {formatNumber(value)}
      </h3>

      {description && (
        <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
          {description}
        </p>
      )}
    </div>
  );
}

function SignalCard({
  title,
  value,
  subtitle,
  tone = "blue",
}: {
  title: string;
  value: number | undefined;
  subtitle: string;
  tone?: MetricTone;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
      <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
        {title}
      </p>

      <div className="mt-2 flex items-end justify-between gap-3">
        <p className={cn("text-2xl font-black", getMetricToneClass(tone))}>
          {formatNumber(value)}
        </p>

        <p className="max-w-[9rem] text-right text-xs leading-5 text-[var(--text-muted)]">
          {subtitle}
        </p>
      </div>
    </div>
  );
}

function WorkflowRunCard({ run }: { run: AiraXWorkflowRun }) {
  return (
    <Link
      href={`/workflows/${run.run_id}`}
      className="group block rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 transition hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-black",
            getStatusClass(run.status)
          )}
        >
          {getStatusIcon(run.status)}
          {run.status || "unknown"}
        </span>

        {run.requires_approval && (
          <span className="inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-black status-warning">
            <ShieldAlert className="h-3.5 w-3.5" />
            approval
          </span>
        )}
      </div>

      <h3 className="line-clamp-1 text-sm font-black text-[var(--text-strong)] group-hover:text-[var(--accent)]">
        {run.user_goal || "Untitled workflow"}
      </h3>

      <p className="mt-2 line-clamp-2 text-xs leading-5 text-[var(--text-muted)]">
        {run.final_answer || run.decision || "No final output recorded yet."}
      </p>

      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="max-w-[12rem] truncate font-mono text-[11px] text-[var(--text-subtle)]">
          {run.run_id}
        </p>

        <ArrowRight className="h-4 w-4 text-[var(--text-subtle)] transition group-hover:translate-x-1 group-hover:text-[var(--accent)]" />
      </div>
    </Link>
  );
}

export default function OverviewPage() {
  const [overview, setOverview] = useState<AiraXOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupMessage, setCleanupMessage] = useState("");
  const [error, setError] = useState("");

  const loadOverview = useCallback(async (options?: { showLoading?: boolean }) => {
    const showLoading = options?.showLoading ?? true;

    try {
      if (showLoading) {
        setLoading(true);
      }

      const data = await getAiraXOverview();

      setOverview(data);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load command center.";

      setError(message);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  async function handleSafeCleanup() {
    const confirmed = window.confirm(
      "Safely remove completed, failed, and rejected workflow history? Active approval, retrying, executing, and approval-processing runs will be skipped."
    );

    if (!confirmed) {
      return;
    }

    try {
      setCleanupLoading(true);
      setCleanupMessage("");
      setError("");

      const result = await deleteSafeAiraXRuns();

      setCleanupMessage(
        `Safe cleanup removed ${result.deleted_count} run${
          result.deleted_count === 1 ? "" : "s"
        } and skipped ${result.skipped_count}.`
      );

      await loadOverview({ showLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Safe cleanup failed.";

      setError(message);
    } finally {
      setCleanupLoading(false);
    }
  }

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const metrics = overview?.workflow_metrics;

  const latestRuns = useMemo(
    () => (metrics?.latest_runs || []).slice().reverse(),
    [metrics?.latest_runs]
  );

  const completionRate = useMemo(() => {
    if (!metrics?.total_runs) {
      return 0;
    }

    return Math.round((metrics.completed_runs / metrics.total_runs) * 100);
  }, [metrics]);

  const activeAttentionCount =
    (metrics?.requires_approval_runs || 0) +
    (metrics?.approval_in_progress_runs || 0);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 grid gap-6 lg:grid-cols-[1fr_23rem]">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              <Activity className="h-3.5 w-3.5" />
              AIRA-X Command Center
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              Command Center
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              Monitor execution health, workflow outcomes, approval queues, Git
              preflights, cleanup activity, and recent autonomous run history
              from one focused dashboard.
            </p>

            {cleanupMessage && (
              <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-3 text-sm font-semibold text-[var(--success)]">
                {cleanupMessage}
              </div>
            )}
          </div>

          <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                <Trash2 className="h-4 w-4" />
              </div>

              <div>
                <h2 className="text-sm font-black text-[var(--text-strong)]">
                  History Maintenance
                </h2>

                <p className="text-xs leading-5 text-[var(--text-muted)]">
                  Remove only safe completed history.
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleSafeCleanup}
              disabled={cleanupLoading || loading}
              className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-4 py-3 text-xs font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {cleanupLoading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {cleanupLoading ? "Cleaning history..." : "Safe Cleanup"}
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
          Loading command center...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && metrics && (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Agents"
              value={overview?.agent_count}
              icon={<BrainCircuit className="h-4 w-4" />}
              tone="blue"
            />

            <MetricCard
              label="Tools"
              value={overview?.tool_count}
              icon={<Wrench className="h-4 w-4" />}
              tone="purple"
            />

            <MetricCard
              label="Workflow Runs"
              value={metrics.total_runs}
              icon={<Workflow className="h-4 w-4" />}
              tone="blue"
            />

            <MetricCard
              label="Tool Calls"
              value={metrics.total_tool_calls}
              icon={<Sparkles className="h-4 w-4" />}
              tone="slate"
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-5 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Workflow Outcomes
                  </h2>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Completion, failures, approvals, and stopped runs.
                  </p>
                </div>

                <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-3 text-right">
                  <p className="text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
                    Completion rate
                  </p>

                  <p className="mt-1 text-2xl font-black text-[var(--success)]">
                    {completionRate}%
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <SignalCard
                  title="Completed"
                  value={metrics.completed_runs}
                  subtitle="Successful final state"
                  tone="green"
                />
                <SignalCard
                  title="Failed"
                  value={metrics.failed_runs}
                  subtitle="Needs inspection"
                  tone="red"
                />
                <SignalCard
                  title="Needs Approval"
                  value={metrics.requires_approval_runs}
                  subtitle="Waiting on user"
                  tone="orange"
                />
                <SignalCard
                  title="Rejected"
                  value={metrics.rejected_runs}
                  subtitle="Stopped by user"
                  tone="red"
                />
                <SignalCard
                  title="Approval Resolved"
                  value={metrics.approval_resolved_runs}
                  subtitle="Handled decisions"
                  tone="blue"
                />
                <SignalCard
                  title="Active Attention"
                  value={activeAttentionCount}
                  subtitle="Pending or processing"
                  tone="orange"
                />
              </div>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                  <ShieldCheck className="h-4 w-4" />
                </div>

                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Safety Signals
                  </h2>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Approval and recovery health.
                  </p>
                </div>
              </div>

              <div className="grid gap-3">
                <SignalCard
                  title="Approvals In Progress"
                  value={metrics.approval_in_progress_runs}
                  subtitle="Currently executing gated actions"
                  tone="orange"
                />
                <SignalCard
                  title="Approved Actions"
                  value={metrics.approval_approved_runs}
                  subtitle="User allowed continuation"
                  tone="green"
                />
                <SignalCard
                  title="Rejected Actions"
                  value={metrics.approval_rejected_runs}
                  subtitle="User stopped execution"
                  tone="red"
                />
                <SignalCard
                  title="Resume Failures"
                  value={metrics.approval_resume_failed_runs}
                  subtitle="Approval succeeded but resume failed"
                  tone="red"
                />
                <SignalCard
                  title="Stale Recoveries"
                  value={metrics.stale_approval_recovery_runs}
                  subtitle="Deadlocked approvals safely stopped"
                  tone="purple"
                />
              </div>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--secondary-soft)] text-[var(--secondary)]">
                  <GitBranch className="h-4 w-4" />
                </div>

                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Git Preflight Coverage
                  </h2>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Repository-changing actions checked before approval.
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                <SignalCard
                  title="Git Preflights"
                  value={metrics.git_preflight_runs}
                  subtitle="All Git-gated actions"
                  tone="purple"
                />
                <SignalCard
                  title="Write Preflights"
                  value={metrics.git_write_preflight_runs}
                  subtitle="Stage / commit checks"
                  tone="orange"
                />
                <SignalCard
                  title="Push Preflights"
                  value={metrics.git_push_preflight_runs}
                  subtitle="Remote push checks"
                  tone="red"
                />
              </div>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-5 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--success-soft)] text-[var(--success)]">
                  <GitCommit className="h-4 w-4" />
                </div>

                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Cleanup & Audit
                  </h2>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Safe cleanup actions and trace volume.
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <SignalCard
                  title="Cleanup Runs"
                  value={metrics.cleanup_runs}
                  subtitle="Workflows with cleanup"
                  tone="green"
                />
                <SignalCard
                  title="Cleanup Actions"
                  value={metrics.total_cleanup_actions}
                  subtitle="Cleanup operations performed"
                  tone="green"
                />
                <SignalCard
                  title="Total Logs"
                  value={metrics.total_logs}
                  subtitle="Workflow trace events"
                  tone="blue"
                />
                <SignalCard
                  title="Total Retries"
                  value={metrics.total_retries}
                  subtitle="Self-correction attempts"
                  tone="purple"
                />
              </div>
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                  <History className="h-4 w-4" />
                </div>

                <div>
                  <h2 className="text-lg font-black text-[var(--text-strong)]">
                    Latest Workflow Runs
                  </h2>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    Recent execution history and outcomes.
                  </p>
                </div>
              </div>

              <Link
                href="/workflows"
                className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                View all workflows
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>

            {latestRuns.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-8 text-center">
                <p className="text-sm font-semibold text-[var(--text-muted)]">
                  No workflow runs recorded yet.
                </p>
              </div>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {latestRuns.map((run) => (
                  <WorkflowRunCard key={run.run_id} run={run} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
