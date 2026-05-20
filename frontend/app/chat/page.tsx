"use client";

import { useState, type FormEvent } from "react";
import {
  Globe2,
  Cpu,
  Send,
  Sparkles,
  Workflow,
  History,
  ShieldCheck,
  XCircle,
  GitBranch,
  UploadCloud,
} from "lucide-react";
import { CitationList } from "@/components/citation-list";
import {
  type ChatResponse,
  sendChat,
  runAiraX,
  approveAiraX,
  rejectAiraX,
} from "@/lib/api";

type Turn = {
  question: string;
  response?: ChatResponse;
  error?: string;
};

type WorkflowLog = {
  timestamp: string;
  agent: string;
  event: string;
  details: any;
};

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

type AiraXResponse = {
  run_id?: string;
  status: string;
  decision: string;
  final_answer: string | null;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext | null;
  plan: {
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
  }[];
  execution_outputs: any[];
  memory: any;
  workflow_logs?: WorkflowLog[];
};

const knownLogEvents = [
  "workflow_started",
  "planning_started",
  "plan_created",
  "decision_made",
  "safety_check_started",
  "safety_approved",
  "safety_blocked_action",
  "approval_check_started",
  "approval_required",
  "approval_not_required",
  "approval_already_granted",
  "approval_granted_by_user",
  "approval_rejected_by_user",
  "git_staging_cleanup_after_rejection",
  "execution_started",
  "tool_policy_checked",
  "execution_success",
  "execution_failed",
  "execution_waiting_for_approval",
  "execution_blocked_by_safety",
  "reflection_completed",
  "validation_started",
  "validation_success",
  "validation_failed",
  "workflow_waiting_for_approval",
  "workflow_resumed_after_approval",
  "workflow_blocked_by_safety",
  "workflow_stopped_after_rejection",
  "workflow_stopped_non_retryable_failure",
  "workflow_failed_max_retries",
  "workflow_completed",
  "memory_summary_created",
];

function renderLogMessage(log: WorkflowLog) {
  switch (log.event) {
    case "workflow_started":
      return <p>Workflow started for goal: {log.details.user_goal}</p>;

    case "planning_started":
      return <p>Planner started analyzing the user goal.</p>;

    case "plan_created":
      return (
        <p>
          Planner created {log.details.steps?.length || 0} execution step(s).
        </p>
      );

    case "decision_made":
      return (
        <p>
          Decision made: <strong>{log.details.decision}</strong>
        </p>
      );

    case "safety_check_started":
      return <p>Safety check started for action: {log.details.action}</p>;

    case "safety_approved":
      return <p>Safety approved the action.</p>;

    case "safety_blocked_action":
      return (
        <p>
          Safety blocked action: <strong>{log.details.action}</strong>
        </p>
      );

    case "approval_check_started":
      return <p>Approval check started for action: {log.details.action}</p>;

    case "approval_required":
      return (
        <p>
          Approval required before executing:{" "}
          <strong>{log.details.action}</strong>
        </p>
      );

    case "approval_not_required":
      return <p>Approval was not required for this action.</p>;

    case "approval_already_granted":
      return <p>User approval was already granted for this action.</p>;

    case "approval_granted_by_user":
      return (
        <p>
          User approved action:{" "}
          <strong>{log.details.approved_action}</strong>
        </p>
      );

    case "approval_rejected_by_user":
      return (
        <p>
          User rejected action:{" "}
          <strong>{log.details.rejected_action}</strong>
        </p>
      );

    case "git_staging_cleanup_after_rejection":
      return (
        <p>
          AIRA-X automatically unstaged Git changes after the commit approval was
          rejected. Cleanup status:{" "}
          <strong>
            {log.details.cleanup_success ? "successful" : "failed"}
          </strong>
          .
        </p>
      );

    case "execution_started":
      return <p>Execution started for step: {log.details.step_title}</p>;

    case "tool_policy_checked":
      return (
        <p>
          Tool policy checked. Risk level:{" "}
          <strong>{log.details.risk_level || "unknown"}</strong>
        </p>
      );

    case "execution_success":
      return <p>Execution completed successfully.</p>;

    case "execution_failed":
      return (
        <p>
          Execution failed. Error: {log.details.error || "Unknown error"}
        </p>
      );

    case "execution_waiting_for_approval":
      return (
        <p>
          Execution paused while waiting for approval:{" "}
          <strong>{log.details.action}</strong>
        </p>
      );

    case "execution_blocked_by_safety":
      return (
        <p>
          Execution blocked by safety system:{" "}
          <strong>{log.details.action}</strong>
        </p>
      );

    case "reflection_completed":
      return (
        <p>
          Reflection analyzed the failure and prepared retry #
          {log.details.retry_count}.
        </p>
      );

    case "validation_started":
      return <p>Validation started for step: {log.details.step_title}</p>;

    case "validation_success":
      return <p>Validation passed successfully.</p>;

    case "validation_failed":
      return (
        <p>
          Validation failed. Error: {log.details.error || log.details.reason}
        </p>
      );

    case "workflow_waiting_for_approval":
      return <p>Workflow paused and is waiting for user approval.</p>;

    case "workflow_resumed_after_approval":
      return <p>Workflow resumed after user approval.</p>;

    case "workflow_blocked_by_safety":
      return <p>Workflow stopped because safety blocked the action.</p>;

    case "workflow_stopped_after_rejection":
      return <p>Workflow stopped because the user rejected the action.</p>;

    case "workflow_stopped_non_retryable_failure":
      return <p>Workflow stopped because a non-retryable action failed.</p>;

    case "workflow_failed_max_retries":
      return <p>Workflow failed after maximum retries.</p>;

    case "workflow_completed":
      return <p>Workflow completed successfully.</p>;

    case "memory_summary_created":
      return <p>Memory Agent saved a workflow summary.</p>;

    default:
      return <p>{JSON.stringify(log.details)}</p>;
  }
}

function renderGitWritePreflight(context: ApprovalContext) {
  return (
    <div className="mt-4 rounded-2xl border border-orange-200 bg-white p-4">
      <div className="mb-3">
        <h4 className="text-sm font-bold text-orange-900">
          Git Preflight Summary
        </h4>

        <p className="mt-1 text-xs leading-5 text-orange-700">
          Review these repository changes before approving this Git write
          action.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Current Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
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

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Changed Files
        </p>

        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.changed_files?.trim() || "No changed files detected."}
        </pre>
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Diff Summary
        </p>

        <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.diff_summary?.trim() || "No diff summary available."}
        </pre>
      </div>
    </div>
  );
}

function renderGitPushPreflight(context: ApprovalContext) {
  return (
    <div className="mt-4 rounded-2xl border border-red-200 bg-white p-4">
      <div className="mb-3 flex items-start gap-3">
        <div className="rounded-xl bg-red-50 p-2 text-red-700">
          <UploadCloud className="h-4 w-4" />
        </div>

        <div>
          <h4 className="text-sm font-bold text-red-900">
            Git Push Preflight Summary
          </h4>

          <p className="mt-1 text-xs leading-5 text-red-700">
            This action can modify your remote repository. Review the target
            remote, branch, and latest commits before approving.
          </p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Target Remote
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.target_remote || "origin"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Target Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.target_branch || context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Current Branch
          </p>

          <p className="mt-1 text-sm font-semibold text-slate-900">
            {context.branch || "Unknown branch"}
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Git Action
          </p>

          <p className="mt-1 break-words text-sm font-semibold text-slate-900">
            {context.pending_action || "Unknown action"}
          </p>
        </div>
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Branch Tracking Status
        </p>

        <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.status_branch?.trim() || "No branch tracking status available."}
        </pre>
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Remote Info
        </p>

        <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.remote_info?.trim() || "No remote info available."}
        </pre>
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Latest Local Commit
        </p>

        <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.last_commit?.trim() || "No latest commit available."}
        </pre>
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recent Local Commits
        </p>

        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100">
          {context.recent_commits?.trim() || "No recent commits available."}
        </pre>
      </div>
    </div>
  );
}

function renderApprovalContext(context?: ApprovalContext | null) {
  if (!context) return null;

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
    <div className="mt-5 rounded-2xl border border-green-200 bg-green-50 p-5">
      <h3 className="text-sm font-bold text-green-900">Cleanup Actions</h3>

      <p className="mt-2 text-sm leading-6 text-green-800">
        AIRA-X performed cleanup after the workflow was rejected or stopped.
      </p>

      <div className="mt-4 space-y-3">
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
    </div>
  );
}

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [forceWeb, setForceWeb] = useState(false);
  const [loading, setLoading] = useState(false);
  const [airaXLoading, setAiraXLoading] = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [rejectionLoading, setRejectionLoading] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [airaXResponse, setAiraXResponse] = useState<AiraXResponse | null>(
    null
  );

  async function submit(event: FormEvent) {
    event.preventDefault();

    const trimmed = question.trim();
    if (!trimmed) return;

    setQuestion("");
    setLoading(true);
    setTurns((prev) => [...prev, { question: trimmed }]);

    try {
      const response = await sendChat(trimmed, forceWeb || undefined);

      setTurns((prev) =>
        prev.map((turn, index) =>
          index === prev.length - 1 ? { ...turn, response } : turn
        )
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Chat failed.";

      setTurns((prev) =>
        prev.map((turn, index) =>
          index === prev.length - 1 ? { ...turn, error: message } : turn
        )
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleRunAiraX() {
    const trimmed = question.trim();
    if (!trimmed) return;

    setAiraXLoading(true);
    setAiraXResponse(null);

    try {
      const result = await runAiraX(trimmed);
      setAiraXResponse(result);
    } catch (error) {
      console.error("AIRA-X Error:", error);
    } finally {
      setAiraXLoading(false);
    }
  }

  async function handleApproveAiraX() {
    if (!airaXResponse?.run_id) return;

    setApprovalLoading(true);

    try {
      const result = await approveAiraX(airaXResponse.run_id);
      setAiraXResponse(result);
    } catch (error) {
      console.error("AIRA-X Approval Error:", error);
    } finally {
      setApprovalLoading(false);
    }
  }

  async function handleRejectAiraX() {
    if (!airaXResponse?.run_id) return;

    setRejectionLoading(true);

    try {
      const result = await rejectAiraX(airaXResponse.run_id);
      setAiraXResponse(result);
    } catch (error) {
      console.error("AIRA-X Rejection Error:", error);
    } finally {
      setRejectionLoading(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10 flex items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
              <Cpu className="h-3.5 w-3.5" />
              AI-powered research + execution workspace
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              AIRA-X Workspace
            </h1>

            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              Ask questions with AIRA or execute workflows with AIRA-X.
            </p>
          </div>

          <div className="hidden rounded-full border border-blue-100 bg-white px-4 py-2 text-xs font-semibold text-slate-600 shadow-sm sm:block">
            {forceWeb ? "Web search enabled" : "Document-first mode"}
          </div>
        </div>
      </section>

      <div className="flex-1 space-y-5">
        {turns.length === 0 && !airaXResponse && (
          <div className="fade-up rounded-[2rem] border border-dashed border-blue-200 bg-white/80 p-10 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-accent">
              <Sparkles className="h-5 w-5" />
            </div>

            <h2 className="text-xl font-semibold text-slate-950">
              Start with research or execution
            </h2>

            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              Use Send for normal AIRA research. Use Run AIRA-X for autonomous
              workflow execution.
            </p>
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={`${turn.question}-${index}`} className="fade-up space-y-4">
            <div className="ml-auto max-w-2xl rounded-[1.5rem] rounded-tr-md bg-accent px-5 py-3 text-sm leading-6 text-white shadow-lg shadow-blue-600/20">
              {turn.question}
            </div>

            {turn.error && (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {turn.error}
              </div>
            )}

            {turn.response && (
              <div className="sarvam-card rounded-[1.75rem] p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <div className="rounded-xl bg-blue-50 p-2 text-accent">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  AI Answer
                </div>

                <div className="whitespace-pre-wrap text-sm leading-7 text-ink">
                  {turn.response.answer
                    .replace(/^###\s?/gm, "")
                    .replace(/^##\s?/gm, "")
                    .replace(/^#\s?/gm, "")
                    .replace(/\*\*/g, "")
                    .replace(/Sources[\s\S]*/i, "")
                    .trim()}
                </div>

                {turn.response.citations.length > 0 && (
                  <div className="mt-5 rounded-[1.25rem] border border-blue-100 bg-blue-50/40 p-4">
                    <p className="mb-3 text-sm font-semibold text-slate-800">
                      Sources
                    </p>

                    <CitationList citations={turn.response.citations} />
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {airaXResponse && (
          <div className="sarvam-card fade-up rounded-[1.75rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
              <div className="rounded-xl bg-purple-50 p-2 text-purple-600">
                <Workflow className="h-4 w-4" />
              </div>
              AIRA-X Workflow Result
            </div>

            <div className="space-y-2 text-sm text-slate-700">
              <p>
                <strong>Status:</strong> {airaXResponse.status}
              </p>

              <p>
                <strong>Decision:</strong> {airaXResponse.decision}
              </p>

              <p>
                <strong>Final Answer:</strong>{" "}
                {airaXResponse.final_answer || "No final answer yet"}
              </p>
            </div>

            {airaXResponse.requires_approval && (
              <div className="mt-5 rounded-2xl border border-orange-300 bg-orange-50 p-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl bg-orange-100 p-2 text-orange-700">
                    <ShieldCheck className="h-5 w-5" />
                  </div>

                  <div className="flex-1">
                    <h3 className="text-sm font-bold text-orange-900">
                      Approval Required
                    </h3>

                    <p className="mt-2 text-sm leading-6 text-orange-800">
                      AIRA-X paused because this action can modify your
                      environment and needs your permission before continuing.
                    </p>

                    <div className="mt-4 rounded-xl border border-orange-200 bg-white p-3 text-sm text-orange-900">
                      <strong>Pending action:</strong>{" "}
                      {airaXResponse.pending_action || "Unknown action"}
                    </div>

                    {renderApprovalContext(airaXResponse.approval_context)}

                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        type="button"
                        onClick={handleApproveAiraX}
                        disabled={approvalLoading || rejectionLoading}
                        className="rounded-xl bg-orange-600 px-5 py-3 text-sm font-bold text-white shadow-md transition hover:bg-orange-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {approvalLoading
                          ? "Approving and continuing..."
                          : "Approve & Continue"}
                      </button>

                      <button
                        type="button"
                        onClick={handleRejectAiraX}
                        disabled={approvalLoading || rejectionLoading}
                        className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-5 py-3 text-sm font-bold text-red-700 shadow-sm transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <XCircle className="h-4 w-4" />
                        {rejectionLoading ? "Rejecting..." : "Reject Action"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {renderCleanupActions(airaXResponse.memory)}

            <div className="mt-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-900">
                Execution Plan
              </h3>

              {airaXResponse.plan.map((step) => (
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

                  <div className="mt-2 grid gap-1 text-xs text-slate-600 sm:grid-cols-2">
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

                  <div className="mt-3">
                    <p className="mb-2 text-xs font-semibold text-slate-700">
                      Result:
                    </p>

                    {step.result ? (
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-950 p-4 text-xs leading-6 text-slate-100">
                        {step.result}
                      </pre>
                    ) : (
                      <p className="text-xs text-slate-500">No result yet</p>
                    )}
                  </div>

                  {step.error && (
                    <div className="mt-3 rounded-xl border border-red-200 bg-white p-3 text-xs text-red-700">
                      <strong>Error:</strong> {step.error}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {airaXResponse.workflow_logs &&
              airaXResponse.workflow_logs.length > 0 && (
                <div className="mt-6 rounded-2xl border border-purple-100 bg-purple-50/30 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <History className="h-4 w-4 text-purple-600" />
                    Workflow Logs
                  </div>

                  <div className="space-y-3">
                    {airaXResponse.workflow_logs.map((log, index) => (
                      <div
                        key={`${log.timestamp}-${index}`}
                        className="rounded-xl border border-purple-100 bg-white p-3 text-xs text-slate-700"
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

                        <div className="mt-2 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                          {renderLogMessage(log)}

                          {!knownLogEvents.includes(log.event) && (
                            <pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                              {JSON.stringify(log.details, null, 2)}
                            </pre>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
          </div>
        )}

        {loading && (
          <div className="fade-up w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-slate-600 shadow-sm">
            Researching sources...
          </div>
        )}

        {airaXLoading && (
          <div className="fade-up w-fit rounded-full border border-purple-100 bg-white px-5 py-3 text-sm font-medium text-purple-700 shadow-sm">
            Running AIRA-X workflow...
          </div>
        )}
      </div>

      <form
        onSubmit={submit}
        className="sticky bottom-4 rounded-[2rem] border border-blue-100 bg-white/90 p-4 shadow-[0_18px_50px_rgba(37,99,235,0.12)] backdrop-blur-xl"
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question or give AIRA-X a task..."
          className="h-24 w-full resize-none rounded-[1.25rem] border border-blue-100 bg-[#f8fbff] p-4 text-sm text-slate-800 caret-blue-600 outline-none transition-all duration-300 placeholder:text-slate-400 focus:border-accent focus:bg-white focus:shadow-sm"
        />

        <div className="mt-3 flex items-center justify-between gap-3">
          <label className="flex cursor-pointer items-center gap-2 rounded-full bg-blue-50 px-3 py-2 text-sm font-medium text-slate-600">
            <input
              type="checkbox"
              checked={forceWeb}
              onChange={(event) => setForceWeb(event.target.checked)}
              className="accent-blue-600"
            />

            <Globe2 className="h-4 w-4 text-accent" />
            Include web search
          </label>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRunAiraX}
              disabled={
                airaXLoading || loading || approvalLoading || rejectionLoading
              }
              className="inline-flex items-center gap-2 rounded-full bg-purple-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-purple-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Workflow className="h-4 w-4" />
              {airaXLoading ? "Running..." : "Run AIRA-X"}
            </button>

            <button
              disabled={
                loading || airaXLoading || approvalLoading || rejectionLoading
              }
              className="group inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Send className="h-4 w-4 transition-all duration-700 ease-out group-hover:-translate-y-2 group-hover:translate-x-3 group-hover:rotate-12 group-hover:opacity-0" />
              Send
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}