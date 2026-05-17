"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  RefreshCcw,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { getAiraXRuns } from "@/lib/api";

type WorkflowRun = {
  run_id: string;
  user_goal: string;
  status: string;
  decision: string;
  final_answer: string | null;
  current_step: number | null;
  retry_count: number;
  requires_approval: boolean;
  pending_action?: string;
  step_count: number;
  log_count: number;
};

function getStatusIcon(status: string) {
  if (status === "completed") return <CheckCircle2 className="h-5 w-5" />;
  if (status === "failed") return <XCircle className="h-5 w-5" />;
  if (status === "requires_approval") return <ShieldAlert className="h-5 w-5" />;
  if (status === "rejected") return <XCircle className="h-5 w-5" />;

  return <Clock className="h-5 w-5" />;
}

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

export default function WorkflowsPage() {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [runCount, setRunCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  async function loadRuns(isRefresh = false) {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
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
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-purple-200/50 blur-3xl" />

        <div className="relative z-10 flex items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700">
              <Activity className="h-3.5 w-3.5" />
              AIRA-X Workflow History
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              Workflow Runs
            </h1>

            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              View recent AIRA-X executions, approval states, retries, failures,
              and completed autonomous workflows.
            </p>
          </div>

          <button
            type="button"
            onClick={() => loadRuns(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-full bg-purple-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-purple-600/20 transition hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCcw className="h-4 w-4" />
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <div className="sarvam-card rounded-[1.5rem] p-5">
          <p className="text-sm font-semibold text-slate-500">Total Runs</p>
          <h2 className="mt-1 text-3xl font-semibold text-slate-950">
            {runCount}
          </h2>
        </div>

        <div className="sarvam-card rounded-[1.5rem] p-5">
          <p className="text-sm font-semibold text-slate-500">Completed</p>
          <h2 className="mt-1 text-3xl font-semibold text-green-700">
            {runs.filter((run) => run.status === "completed").length}
          </h2>
        </div>

        <div className="sarvam-card rounded-[1.5rem] p-5">
          <p className="text-sm font-semibold text-slate-500">Needs Approval</p>
          <h2 className="mt-1 text-3xl font-semibold text-orange-700">
            {runs.filter((run) => run.status === "requires_approval").length}
          </h2>
        </div>

        <div className="sarvam-card rounded-[1.5rem] p-5">
          <p className="text-sm font-semibold text-slate-500">Failed/Rejected</p>
          <h2 className="mt-1 text-3xl font-semibold text-red-700">
            {
              runs.filter(
                (run) => run.status === "failed" || run.status === "rejected"
              ).length
            }
          </h2>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-purple-100 bg-white px-5 py-3 text-sm font-medium text-purple-700 shadow-sm">
          Loading workflow history...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div className="rounded-[2rem] border border-dashed border-purple-200 bg-white/80 p-10 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-purple-50 text-purple-600">
            <Activity className="h-5 w-5" />
          </div>

          <h2 className="text-xl font-semibold text-slate-950">
            No workflow runs yet
          </h2>

          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
            Run AIRA-X from the chat page first, then come back here to view
            workflow history.
          </p>
        </div>
      )}

      {!loading && !error && runs.length > 0 && (
        <section className="space-y-4">
          {runs.map((run) => (
            <div
              key={run.run_id}
              className="sarvam-card rounded-[1.5rem] p-5"
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${getStatusStyle(
                        run.status
                      )}`}
                    >
                      {getStatusIcon(run.status)}
                      {run.status}
                    </span>

                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                      Retries: {run.retry_count}
                    </span>

                    <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                      Steps: {run.step_count}
                    </span>

                    <span className="rounded-full bg-purple-50 px-3 py-1 text-xs font-medium text-purple-700">
                      Logs: {run.log_count}
                    </span>
                  </div>

                  <h3 className="text-lg font-semibold text-slate-950">
                    {run.user_goal}
                  </h3>

                  <p className="mt-2 text-sm text-slate-600">
                    <strong>Decision:</strong> {run.decision}
                  </p>

                  <p className="mt-1 text-sm text-slate-600">
                    <strong>Final Answer:</strong>{" "}
                    {run.final_answer || "No final answer yet"}
                  </p>

                  {run.pending_action && (
                    <div className="mt-3 rounded-xl border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800">
                      <strong>Pending action:</strong> {run.pending_action}
                    </div>
                  )}
                </div>

                <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
                  <p className="font-semibold text-slate-700">Run ID</p>
                  <p className="mt-1 max-w-xs break-all">{run.run_id}</p>
                </div>
              </div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}