"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  FileText,
  History,
  ShieldAlert,
  Terminal,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { getAiraXRun } from "@/lib/api";

type WorkflowLog = {
  timestamp: string;
  agent: string;
  event: string;
  details: any;
};

type WorkflowStep = {
  id: number;
  title: string;
  description: string;
  status: string;
  assigned_agent: string;
  tool_name?: string | null;
  tool_action?: string | null;
  tool_payload?: any;
  result?: string | null;
  error?: string | null;
};

type WorkflowRun = {
  run_id: string;
  status: string;
  decision: string;
  final_answer: string | null;
  plan: WorkflowStep[];
  execution_outputs: any[];
  memory: any;
  workflow_logs: WorkflowLog[];
  workflow_summary: any;
  requires_approval: boolean;
  pending_action?: string;
};

function getStatusIcon(status: string) {
  if (status === "completed") return <CheckCircle2 className="h-5 w-5" />;
  if (status === "failed" || status === "rejected") {
    return <XCircle className="h-5 w-5" />;
  }
  if (status === "requires_approval") {
    return <ShieldAlert className="h-5 w-5" />;
  }

  return <Activity className="h-5 w-5" />;
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

export default function WorkflowDetailsPage() {
  const params = useParams<{ run_id: string }>();
  const runId = params.run_id;

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadRun() {
      try {
        setLoading(true);

        const data = await getAiraXRun(runId);

        if (!data.success) {
          setError(data.error || "Workflow run not found.");
          return;
        }

        setRun(data.run);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to load workflow run.";

        setError(message);
      } finally {
        setLoading(false);
      }
    }

    if (runId) {
      loadRun();
    }
  }, [runId]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-purple-200/50 blur-3xl" />

        <div className="relative z-10">
          <Link
            href="/workflows"
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700 transition hover:bg-purple-100"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Workflow Runs
          </Link>

          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700">
            <Activity className="h-3.5 w-3.5" />
            AIRA-X Workflow Details
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Workflow Run Details
          </h1>

          <p className="mt-2 max-w-3xl break-all text-sm leading-6 text-slate-600">
            Run ID: {runId}
          </p>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-purple-100 bg-white px-5 py-3 text-sm font-medium text-purple-700 shadow-sm">
          Loading workflow details...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && run && (
        <>
          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <span
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${getStatusStyle(
                    run.status
                  )}`}
                >
                  {getStatusIcon(run.status)}
                  {run.status}
                </span>

                <h2 className="mt-4 text-xl font-semibold text-slate-950">
                  {run.memory?.workflow_summary?.user_goal || "Workflow Run"}
                </h2>

                <p className="mt-2 text-sm text-slate-600">
                  <strong>Decision:</strong> {run.decision}
                </p>

                <p className="mt-1 text-sm text-slate-600">
                  <strong>Final Answer:</strong>{" "}
                  {run.final_answer || "No final answer yet"}
                </p>

                {run.pending_action && (
                  <div className="mt-4 rounded-xl border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800">
                    <strong>Pending action:</strong> {run.pending_action}
                  </div>
                )}
              </div>

              <div className="grid gap-3 text-sm sm:grid-cols-3">
                <div className="rounded-2xl bg-blue-50 p-4 text-blue-700">
                  <p className="font-semibold">Steps</p>
                  <p className="mt-1 text-2xl font-bold">
                    {run.plan.length}
                  </p>
                </div>

                <div className="rounded-2xl bg-purple-50 p-4 text-purple-700">
                  <p className="font-semibold">Logs</p>
                  <p className="mt-1 text-2xl font-bold">
                    {run.workflow_logs.length}
                  </p>
                </div>

                <div className="rounded-2xl bg-slate-50 p-4 text-slate-700">
                  <p className="font-semibold">Tool Calls</p>
                  <p className="mt-1 text-2xl font-bold">
                    {run.execution_outputs.length}
                  </p>
                </div>
              </div>
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <ClipboardList className="h-4 w-4 text-purple-600" />
              Execution Plan
            </div>

            <div className="space-y-3">
              {run.plan.map((step) => (
                <div
                  key={step.id}
                  className={`rounded-2xl border p-4 text-sm ${
                    step.status === "failed" ||
                    step.status === "blocked" ||
                    step.status === "rejected"
                      ? "border-red-200 bg-red-50/60"
                      : "border-blue-100 bg-blue-50/30"
                  }`}
                >
                  <p className="font-semibold text-slate-900">
                    {step.id}. {step.title}
                  </p>

                  <p className="mt-1 text-slate-600">{step.description}</p>

                  <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-4">
                    <p>
                      <strong>Status:</strong> {step.status}
                    </p>

                    <p>
                      <strong>Agent:</strong> {step.assigned_agent}
                    </p>

                    <p>
                      <strong>Tool:</strong> {step.tool_name || "None"}
                    </p>

                    <p>
                      <strong>Action:</strong> {step.tool_action || "None"}
                    </p>
                  </div>

                  {step.result && (
                    <div className="mt-3 rounded-xl bg-white p-3 text-xs text-slate-700">
                      <strong>Result:</strong>
                      <pre className="mt-2 whitespace-pre-wrap break-words">
                        {step.result}
                      </pre>
                    </div>
                  )}

                  {step.error && (
                    <div className="mt-3 rounded-xl border border-red-200 bg-white p-3 text-xs text-red-700">
                      <strong>Error:</strong> {step.error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Terminal className="h-4 w-4 text-purple-600" />
              Tool Execution Outputs
            </div>

            {run.execution_outputs.length === 0 ? (
              <p className="text-sm text-slate-500">
                No tool execution outputs recorded for this run.
              </p>
            ) : (
              <div className="space-y-3">
                {run.execution_outputs.map((output, index) => (
                  <div
                    key={index}
                    className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-700"
                  >
                    <p>
                      <strong>Agent:</strong> {output.agent}
                    </p>
                    <p>
                      <strong>Tool:</strong> {output.tool_used}
                    </p>
                    <p>
                      <strong>Action:</strong> {output.tool_action}
                    </p>

                    <pre className="mt-3 max-h-72 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                      {JSON.stringify(output.tool_result, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <History className="h-4 w-4 text-purple-600" />
              Workflow Logs
            </div>

            <div className="space-y-3">
              {run.workflow_logs.map((log, index) => (
                <div
                  key={`${log.timestamp}-${index}`}
                  className="rounded-2xl border border-purple-100 bg-purple-50/30 p-4 text-xs text-slate-700"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-slate-900">
                      {log.agent}
                    </p>

                    <p className="text-slate-400">
                      {new Date(log.timestamp).toLocaleString()}
                    </p>
                  </div>

                  <p className="mt-1">
                    <strong>Event:</strong> {log.event}
                  </p>

                  <pre className="mt-3 max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                    {JSON.stringify(log.details, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <FileText className="h-4 w-4 text-purple-600" />
              Memory Summary
            </div>

            <pre className="max-h-96 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">
              {JSON.stringify(run.workflow_summary || {}, null, 2)}
            </pre>
          </section>
        </>
      )}
    </div>
  );
}