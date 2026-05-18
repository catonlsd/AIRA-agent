"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  GitBranch,
  ShieldAlert,
  Wrench,
  XCircle,
} from "lucide-react";
import { getAiraXOverview } from "@/lib/api";

type LatestRun = {
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

type OverviewResponse = {
  platform: string;
  focus: string;
  status: string;
  agent_count: number;
  tool_count: number;
  workflow_metrics: {
    total_runs: number;
    completed_runs: number;
    failed_runs: number;
    requires_approval_runs: number;
    rejected_runs: number;
    total_retries: number;
    total_tool_calls: number;
    total_logs: number;
    latest_runs: LatestRun[];
  };
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

export default function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadOverview() {
    try {
      setLoading(true);

      const data = await getAiraXOverview();

      setOverview(data);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load overview.";

      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadOverview();
  }, []);

  const metrics = overview?.workflow_metrics;

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
              <Activity className="h-3.5 w-3.5" />
              AIRA-X Platform Dashboard
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              Overview Dashboard
            </h1>

            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Monitor AIRA-X agents, tools, workflow runs, retries, approvals,
              execution activity, and platform health.
            </p>
          </div>

          {overview && (
            <div className="rounded-2xl border border-green-100 bg-green-50 px-4 py-3 text-sm font-semibold text-green-700">
              Status: {overview.status}
            </div>
          )}
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-blue-700 shadow-sm">
          Loading platform overview...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && overview && metrics && (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-500">
                    Agents
                  </p>
                  <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                    {overview.agent_count}
                  </h2>
                </div>

                <div className="rounded-2xl bg-blue-50 p-3 text-blue-600">
                  <BrainCircuit className="h-6 w-6" />
                </div>
              </div>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-500">Tools</p>
                  <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                    {overview.tool_count}
                  </h2>
                </div>

                <div className="rounded-2xl bg-purple-50 p-3 text-purple-600">
                  <Wrench className="h-6 w-6" />
                </div>
              </div>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-500">
                    Workflow Runs
                  </p>
                  <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                    {metrics.total_runs}
                  </h2>
                </div>

                <div className="rounded-2xl bg-blue-50 p-3 text-blue-600">
                  <GitBranch className="h-6 w-6" />
                </div>
              </div>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-500">
                    Tool Calls
                  </p>
                  <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                    {metrics.total_tool_calls}
                  </h2>
                </div>

                <div className="rounded-2xl bg-slate-50 p-3 text-slate-600">
                  <Cpu className="h-6 w-6" />
                </div>
              </div>
            </div>
          </section>

          <section className="grid gap-4 md:grid-cols-4">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">Completed</p>
              <h2 className="mt-1 text-3xl font-semibold text-green-700">
                {metrics.completed_runs}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">Failed</p>
              <h2 className="mt-1 text-3xl font-semibold text-red-700">
                {metrics.failed_runs}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Needs Approval
              </p>
              <h2 className="mt-1 text-3xl font-semibold text-orange-700">
                {metrics.requires_approval_runs}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">Rejected</p>
              <h2 className="mt-1 text-3xl font-semibold text-red-700">
                {metrics.rejected_runs}
              </h2>
            </div>
          </section>

          <section className="grid gap-4 md:grid-cols-3">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Total Retries
              </p>
              <h2 className="mt-1 text-3xl font-semibold text-purple-700">
                {metrics.total_retries}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Total Logs
              </p>
              <h2 className="mt-1 text-3xl font-semibold text-blue-700">
                {metrics.total_logs}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Storage Mode
              </p>
              <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                <Database className="h-4 w-4" />
                Local JSON
              </div>
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Activity className="h-4 w-4 text-blue-600" />
              Latest Workflow Runs
            </div>

            {metrics.latest_runs.length === 0 ? (
              <p className="text-sm text-slate-500">
                No workflow runs recorded yet.
              </p>
            ) : (
              <div className="space-y-3">
                {metrics.latest_runs.map((run) => (
                  <div
                    key={run.run_id}
                    className="rounded-2xl border border-blue-100 bg-blue-50/30 p-4"
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div>
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
                            Retries: {run.retry_count}
                          </span>

                          <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                            Logs: {run.log_count}
                          </span>
                        </div>

                        <h3 className="text-sm font-semibold text-slate-950">
                          {run.user_goal}
                        </h3>

                        <p className="mt-1 text-xs text-slate-600">
                          <strong>Decision:</strong> {run.decision}
                        </p>

                        <p className="mt-1 text-xs text-slate-600">
                          <strong>Final Answer:</strong>{" "}
                          {run.final_answer || "No final answer yet"}
                        </p>
                      </div>

                      <p className="max-w-xs break-all rounded-xl bg-white p-3 text-[11px] text-slate-500">
                        {run.run_id}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}