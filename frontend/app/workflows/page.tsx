"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  CheckCircle2,
  Clock,
  GitBranch,
  ShieldAlert,
  Workflow,
  XCircle,
} from "lucide-react";
import { getAiraXRuns } from "@/lib/api";

type ApprovalContext = {
  type?: string;
  tool_name?: string;
  tool_action?: string;
  pending_action?: string;
  commit_message?: string | null;
  branch?: string;
  changed_files?: string;
  diff_summary?: string;
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
  decision: string;
  final_answer: string | null;
  current_step: number | null;
  retry_count: number;
  requires_approval: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext;
  approval_context_type?: string;
  cleanup_actions?: CleanupAction[];
  cleanup_count?: number;
  has_cleanup?: boolean;
  step_count: number;
  log_count: number;
};

function getStatusStyle(status: string) {
  if (status === "completed") {
    return "border-green-200 bg-green-50 text-green-700";
  }

  if (status === "failed" || status === "rejected") {
    return "border-red-200 bg-red-50 text-red-700";
  }

  if (status === "requires_approval") {
    return "border-orange-200 bg-orange-50 text-orange-700";
  }

  return "border-blue-200 bg-blue-50 text-blue-700";
}

function getStatusIcon(status: string) {
  if (status === "completed") {
    return <CheckCircle2 className="h-4 w-4" />;
  }

  if (status === "failed" || status === "rejected") {
    return <XCircle className="h-4 w-4" />;
  }

  if (status === "requires_approval") {
    return <ShieldAlert className="h-4 w-4" />;
  }

  return <Clock className="h-4 w-4" />;
}

function hasGitPreflight(run: WorkflowRunSummary) {
  return (
    run.approval_context_type === "git_write_preflight" ||
    run.approval_context?.type === "git_write_preflight"
  );
}

export default function WorkflowsPage() {
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadRuns() {
    try {
      setLoading(true);

      const data = await getAiraXRuns();

      setRuns(data.runs || []);
      setRunCount(data.run_count || 0);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load workflow runs.";

      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  const cleanupRunCount = runs.filter((run) => run.has_cleanup).length;

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700">
            <Workflow className="h-3.5 w-3.5" />
            AIRA-X Workflow History
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Workflow Runs
          </h1>

          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Review previous AIRA-X workflow executions, approval states,
            decisions, retry counts, Git preflight summaries, cleanup actions,
            and execution outcomes.
          </p>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-blue-700 shadow-sm">
          Loading workflow runs...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Total Runs
              </p>

              <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                {runCount}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Approval Runs
              </p>

              <h2 className="mt-1 text-3xl font-semibold text-orange-700">
                {runs.filter((run) => run.requires_approval).length}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Git Preflights
              </p>

              <h2 className="mt-1 text-3xl font-semibold text-purple-700">
                {runs.filter((run) => hasGitPreflight(run)).length}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Cleanups
              </p>

              <h2 className="mt-1 text-3xl font-semibold text-green-700">
                {cleanupRunCount}
              </h2>
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Activity className="h-4 w-4 text-blue-600" />
              Recent Workflow Runs
            </div>

            {runs.length === 0 ? (
              <p className="text-sm text-slate-500">
                No workflow runs recorded yet.
              </p>
            ) : (
              <div className="space-y-3">
                {runs
                  .slice()
                  .reverse()
                  .map((run) => {
                    const gitPreflight = hasGitPreflight(run);
                    const cleanupPerformed = Boolean(run.has_cleanup);

                    return (
                      <Link
                        key={run.run_id}
                        href={`/workflows/${run.run_id}`}
                        className="block rounded-2xl border border-blue-100 bg-blue-50/30 p-4 transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50"
                      >
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="min-w-0 flex-1">
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <span
                                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${getStatusStyle(
                                  run.status
                                )}`}
                              >
                                {getStatusIcon(run.status)}
                                {run.status}
                              </span>

                              <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                                Decision: {run.decision}
                              </span>

                              <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                                Steps: {run.step_count}
                              </span>

                              <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                                Logs: {run.log_count}
                              </span>

                              {gitPreflight && (
                                <span className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-700">
                                  <ShieldAlert className="h-3.5 w-3.5" />
                                  Git Preflight Available
                                </span>
                              )}

                              {cleanupPerformed && (
                                <span className="inline-flex items-center gap-2 rounded-full border border-green-200 bg-green-50 px-3 py-1 text-xs font-semibold text-green-700">
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  Cleanup Performed
                                </span>
                              )}
                            </div>

                            <h3 className="truncate text-sm font-semibold text-slate-950">
                              {run.user_goal}
                            </h3>

                            <p className="mt-1 text-xs text-slate-600">
                              <strong>Final Answer:</strong>{" "}
                              {run.final_answer || "No final answer yet"}
                            </p>

                            {run.pending_action && (
                              <p className="mt-1 text-xs text-slate-600">
                                <strong>Pending Action:</strong>{" "}
                                {run.pending_action}
                              </p>
                            )}

                            {gitPreflight && (
                              <div className="mt-3 rounded-xl border border-orange-100 bg-white p-3">
                                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-orange-700">
                                  <GitBranch className="h-3.5 w-3.5" />
                                  Git Approval Preview
                                </div>

                                <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                                  <p>
                                    <strong>Branch:</strong>{" "}
                                    {run.approval_context?.branch ||
                                      "Unknown branch"}
                                  </p>

                                  <p>
                                    <strong>Action:</strong>{" "}
                                    {run.approval_context?.pending_action ||
                                      run.pending_action ||
                                      "Unknown action"}
                                  </p>
                                </div>
                              </div>
                            )}

                            {cleanupPerformed && (
                              <div className="mt-3 rounded-xl border border-green-100 bg-white p-3">
                                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-green-700">
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  Cleanup Summary
                                </div>

                                <div className="space-y-2 text-xs text-slate-600">
                                  <p>
                                    <strong>Cleanup Count:</strong>{" "}
                                    {run.cleanup_count || 0}
                                  </p>

                                  {run.cleanup_actions?.[0] && (
                                    <>
                                      <p>
                                        <strong>Action:</strong>{" "}
                                        {run.cleanup_actions[0].tool_name}:
                                        {run.cleanup_actions[0].tool_action}
                                      </p>

                                      <p>
                                        <strong>Status:</strong>{" "}
                                        {run.cleanup_actions[0].result?.success
                                          ? "successful"
                                          : "failed"}
                                      </p>
                                    </>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>

                          <p className="max-w-xs break-all rounded-xl bg-white p-3 text-[11px] text-slate-500">
                            {run.run_id}
                          </p>
                        </div>
                      </Link>
                    );
                  })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}