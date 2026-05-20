"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Clock,
  GitBranch,
  History,
  ShieldAlert,
  UploadCloud,
  Workflow,
  XCircle,
} from "lucide-react";
import { getAiraXRun } from "@/lib/api";

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

  branch_success?: boolean;
  status_success?: boolean;
  diff_success?: boolean;
  status_branch_success?: boolean;
  remote_info_success?: boolean;
  last_commit_success?: boolean;
  recent_commits_success?: boolean;
};

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
  workflow_logs?: WorkflowLog[];
  workflow_summary?: any;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext | null;
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

function renderGitWritePreflight(context: ApprovalContext) {
  return (
    <section className="sarvam-card rounded-[1.5rem] border border-orange-200 bg-orange-50/40 p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-orange-900">
        <ShieldAlert className="h-4 w-4" />
        Git Preflight Summary
      </div>

      <p className="mb-4 text-sm leading-6 text-orange-800">
        This workflow required approval for a Git write action. AIRA-X captured
        the repository state before asking for permission.
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Current Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Git Action
          </p>

          <p className="mt-1 break-words text-sm font-semibold text-slate-900">
            {context.pending_action || "Unknown action"}
          </p>
        </div>
      </div>

      {context.commit_message && (
        <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
            Commit Message
          </p>

          <p className="mt-1 text-sm font-semibold text-blue-900">
            {context.commit_message}
          </p>
        </div>
      )}

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Changed Files
        </p>

        <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.changed_files?.trim() || "No changed files detected."}
        </pre>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Diff Summary
        </p>

        <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.diff_summary?.trim() || "No diff summary available."}
        </pre>
      </div>
    </section>
  );
}

function renderGitPushPreflight(context: ApprovalContext) {
  return (
    <section className="sarvam-card rounded-[1.5rem] border border-red-200 bg-red-50/40 p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-red-900">
        <UploadCloud className="h-4 w-4" />
        Git Push Preflight Summary
      </div>

      <p className="mb-4 text-sm leading-6 text-red-800">
        This workflow required approval for a remote Git push. AIRA-X captured
        the target remote, branch, tracking status, and recent commits before
        asking for permission.
      </p>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Target Remote
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.target_remote || "origin"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Target Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.target_branch || context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Current Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Git Action
          </p>

          <p className="mt-1 break-words text-sm font-semibold text-slate-900">
            {context.pending_action || "Unknown action"}
          </p>
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Branch Tracking Status
        </p>

        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.status_branch?.trim() ||
            "No branch tracking status available."}
        </pre>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Remote Info
        </p>

        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.remote_info?.trim() || "No remote info available."}
        </pre>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Latest Local Commit
        </p>

        <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.last_commit?.trim() || "No latest commit available."}
        </pre>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recent Local Commits
        </p>

        <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {context.recent_commits?.trim() || "No recent commits available."}
        </pre>
      </div>
    </section>
  );
}

function renderApprovalContext(context?: ApprovalContext | null) {
  if (!context) {
    return null;
  }

  if (context.type === "git_write_preflight") {
    return renderGitWritePreflight(context);
  }

  if (context.type === "git_push_preflight") {
    return renderGitPushPreflight(context);
  }

  return null;
}

function renderCleanupActions(memory: any) {
  const cleanupActions = memory?.cleanup_actions || [];

  if (!Array.isArray(cleanupActions) || cleanupActions.length === 0) {
    return null;
  }

  return (
    <section className="sarvam-card rounded-[1.5rem] border border-green-200 bg-green-50/40 p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-green-900">
        <CheckCircle2 className="h-4 w-4" />
        Cleanup Actions
      </div>

      <p className="mb-4 text-sm leading-6 text-green-800">
        AIRA-X performed cleanup after the workflow was rejected or stopped.
      </p>

      <div className="space-y-3">
        {cleanupActions.map((cleanup: any, index: number) => (
          <div
            key={`${cleanup.tool_action}-${index}`}
            className="rounded-xl border border-green-200 bg-white p-3 text-xs text-green-900"
          >
            <p>
              <strong>Action:</strong> {cleanup.tool_name}:{cleanup.tool_action}
            </p>

            <p className="mt-1">
              <strong>Reason:</strong> {cleanup.reason}
            </p>

            <p className="mt-1">
              <strong>Status:</strong>{" "}
              {cleanup.result?.success ? "successful" : "failed"}
            </p>

            {cleanup.result?.command && (
              <p className="mt-1">
                <strong>Command:</strong> {cleanup.result.command}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function WorkflowDetailPage() {
  const params = useParams();
  const runIdParam = params?.run_id;
  const runId = Array.isArray(runIdParam) ? runIdParam[0] : runIdParam;

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadRun() {
    if (!runId) return;

    try {
      setLoading(true);

      const data = await getAiraXRun(runId);

      if (!data.success) {
        setError(data.error || "Workflow run not found.");
        setRun(null);
        return;
      }

      setRun(data.run);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load workflow run.";

      setError(message);
      setRun(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRun();
  }, [runId]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10">
          <Link
            href="/workflows"
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Workflow Runs
          </Link>

          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700">
            <Workflow className="h-3.5 w-3.5" />
            AIRA-X Workflow Detail
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Workflow Run
          </h1>

          <p className="mt-2 max-w-3xl break-all text-sm leading-6 text-slate-600">
            {runId}
          </p>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-blue-700 shadow-sm">
          Loading workflow run...
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
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <span
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${getStatusStyle(
                  run.status
                )}`}
              >
                {getStatusIcon(run.status)}
                {run.status}
              </span>

              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                Decision: {run.decision}
              </span>

              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                Steps: {run.plan.length}
              </span>

              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                Logs: {run.workflow_logs?.length || 0}
              </span>
            </div>

            <div className="space-y-2 text-sm text-slate-700">
              <p>
                <strong>Final Answer:</strong>{" "}
                {run.final_answer || "No final answer yet"}
              </p>

              {run.pending_action && (
                <p>
                  <strong>
                    {run.status === "rejected"
                      ? "Rejected Action"
                      : run.status === "requires_approval"
                        ? "Pending Action"
                        : "Action"}
                    :
                  </strong>{" "}
                  {run.pending_action}
                </p>
              )}
            </div>
          </section>

          {renderApprovalContext(run.approval_context)}

          {renderCleanupActions(run.memory)}

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <GitBranch className="h-4 w-4 text-blue-600" />
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

                  <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                    <p>
                      <strong>Status:</strong> {step.status}
                    </p>

                    <p>
                      <strong>Agent:</strong> {step.assigned_agent}
                    </p>

                    {step.tool_name && (
                      <p>
                        <strong>Tool:</strong> {step.tool_name}
                      </p>
                    )}

                    {step.tool_action && (
                      <p>
                        <strong>Action:</strong> {step.tool_action}
                      </p>
                    )}
                  </div>

                  {step.result && (
                    <div className="mt-3">
                      <p className="mb-2 text-xs font-semibold text-slate-700">
                        Result:
                      </p>

                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-950 p-4 text-xs leading-6 text-slate-100">
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

          {run.workflow_logs && run.workflow_logs.length > 0 && (
            <section className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
                <History className="h-4 w-4 text-purple-600" />
                Workflow Logs
              </div>

              <div className="space-y-3">
                {run.workflow_logs.map((log, index) => (
                  <div
                    key={`${log.timestamp}-${index}`}
                    className="rounded-xl border border-purple-100 bg-purple-50/30 p-3 text-xs text-slate-700"
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

                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                      {JSON.stringify(log.details, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Activity className="h-4 w-4 text-blue-600" />
              Raw Execution Outputs
            </div>

            {run.execution_outputs.length === 0 ? (
              <p className="text-sm text-slate-500">
                No execution outputs recorded.
              </p>
            ) : (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">
                {JSON.stringify(run.execution_outputs, null, 2)}
              </pre>
            )}
          </section>
        </>
      )}
    </div>
  );
}