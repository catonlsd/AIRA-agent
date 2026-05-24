"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  FileUp,
  GitBranch,
  Globe2,
  History,
  Send,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Workflow,
  XCircle,
} from "lucide-react";
import { CitationList } from "@/components/citation-list";
import {
  type ChatResponse,
  approveAiraX,
  rejectAiraX,
  runAiraX,
  sendChat,
  uploadDocuments,
} from "@/lib/api";
import { useAiraMode } from "@/components/mode-provider";
import { cn } from "@/lib/utils";

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

function getWorkflowStatusClass(status?: string) {
  if (status === "completed") {
    return "status-success";
  }

  if (status === "failed" || status === "rejected" || status === "blocked") {
    return "status-danger";
  }

  if (status === "requires_approval" || status === "retrying") {
    return "status-warning";
  }

  return "status-info";
}

function cleanAnswer(answer: string) {
  return answer
    .replace(/^###\s?/gm, "")
    .replace(/^##\s?/gm, "")
    .replace(/^#\s?/gm, "")
    .replace(/\*\*/g, "")
    .replace(/Sources[\s\S]*/i, "")
    .trim();
}

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

function renderInfoTile(label: string, value: string) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
        {label}
      </p>

      <p className="mt-1 break-words text-sm font-semibold text-[var(--text-strong)]">
        {value}
      </p>
    </div>
  );
}

function renderCodeBlock(value?: string, fallback = "No data available.") {
  return (
    <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-xl p-3 text-xs leading-5">
      {value?.trim() || fallback}
    </pre>
  );
}

function renderGitWritePreflight(context: ApprovalContext) {
  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-4">
      <div className="mb-3">
        <h4 className="text-sm font-bold text-[var(--warning)]">
          Git Preflight Summary
        </h4>

        <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
          Review these repository changes before approving this Git write
          action.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {renderInfoTile("Current Branch", context.branch || "Unknown branch")}
        {renderInfoTile("Git Action", context.pending_action || "Unknown action")}
      </div>

      {context.commit_message && (
        <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--accent)]">
            Commit Message
          </p>

          <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
            {context.commit_message}
          </p>
        </div>
      )}

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Changed Files
        </p>

        {renderCodeBlock(context.changed_files, "No changed files detected.")}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Diff Summary
        </p>

        {renderCodeBlock(context.diff_summary, "No diff summary available.")}
      </div>
    </div>
  );
}

function renderGitPushPreflight(context: ApprovalContext) {
  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4">
      <div className="mb-3 flex items-start gap-3">
        <div className="rounded-xl border border-[color-mix(in_srgb,var(--danger)_28%,transparent)] bg-[var(--surface-soft)] p-2 text-[var(--danger)]">
          <UploadCloud className="h-4 w-4" />
        </div>

        <div>
          <h4 className="text-sm font-bold text-[var(--danger)]">
            Git Push Preflight Summary
          </h4>

          <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
            This action can modify your remote repository. Review the target
            remote, branch, and latest commits before approving.
          </p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {renderInfoTile("Target Remote", context.target_remote || "origin")}
        {renderInfoTile(
          "Target Branch",
          context.target_branch || context.branch || "Unknown branch"
        )}
        {renderInfoTile("Current Branch", context.branch || "Unknown branch")}
        {renderInfoTile("Git Action", context.pending_action || "Unknown action")}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Branch Tracking Status
        </p>

        {renderCodeBlock(
          context.status_branch,
          "No branch tracking status available."
        )}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Remote Info
        </p>

        {renderCodeBlock(context.remote_info, "No remote info available.")}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Latest Local Commit
        </p>

        {renderCodeBlock(context.last_commit, "No latest commit available.")}
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-subtle)]">
          Recent Local Commits
        </p>

        {renderCodeBlock(context.recent_commits, "No recent commits available.")}
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
    <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-5">
      <h3 className="text-sm font-bold text-[var(--success)]">
        Cleanup Actions
      </h3>

      <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
        AIRA-X performed cleanup after the workflow was rejected or stopped.
      </p>

      <div className="mt-4 space-y-3">
        {cleanupActions.map((cleanup: any, index: number) => (
          <div
            key={`${cleanup.tool_action}-${index}`}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-xs text-[var(--text)]"
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
  const { mode } = useAiraMode();
  const isAiraMode = mode === "aira";

  const [question, setQuestion] = useState("");
  const [forceWeb, setForceWeb] = useState(false);
  const [loading, setLoading] = useState(false);
  const [airaXLoading, setAiraXLoading] = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [rejectionLoading, setRejectionLoading] = useState(false);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [airaXResponse, setAiraXResponse] = useState<AiraXResponse | null>(
    null
  );

  const busy =
    loading ||
    airaXLoading ||
    approvalLoading ||
    rejectionLoading ||
    uploadLoading;

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
      setQuestion("");
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

  async function handleUploadDocuments(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;

    if (!files || files.length === 0) {
      return;
    }

    setUploadLoading(true);
    setUploadMessage("");
    setUploadError("");

    try {
      const result = await uploadDocuments(files);
      const count = result.documents?.length || files.length;

      setUploadMessage(
        `${count} document${count === 1 ? "" : "s"} uploaded and indexed.`
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Document upload failed.";

      setUploadError(message);
    } finally {
      setUploadLoading(false);
      event.target.value = "";
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-5">
      <section className="sarvam-card fade-up relative rounded-[1.75rem] p-5">
        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-3 px-3 py-1.5 text-xs font-bold">
              <Cpu className="h-3.5 w-3.5" />
              {isAiraMode ? "Research workspace" : "Execute workspace"}
            </div>

            <h1 className="aira-gradient-text text-3xl font-black tracking-tight">
              {isAiraMode ? "Ask AIRA" : "Execution Panel"}
            </h1>

            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
              {isAiraMode
                ? "Ask document-backed research questions, upload knowledge, and get grounded answers with citations."
                : "Workflow results, approval checkpoints, execution plans, and logs appear here when you run AIRA-X."}
            </p>
          </div>

          {isAiraMode && (
            <div className="lg:w-56">
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3">
                <p className="text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
                  Mode
                </p>

                <p className="mt-1 text-sm font-bold text-[var(--text-strong)]">
                  {forceWeb ? "Web enabled" : "Document-first"}
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="grid flex-1 gap-5 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="flex min-h-[520px] flex-col gap-4">
          {turns.length === 0 && !airaXResponse && (
            <div className="aira-panel fade-up flex min-h-[300px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <Sparkles className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-bold text-[var(--text-strong)]">
                {isAiraMode
                  ? "Ask from your knowledge base"
                  : "Ready to execute a workflow"}
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                {isAiraMode
                  ? "Upload documents, ask focused questions, and let AIRA return grounded answers with source-backed context."
                  : "Describe the task you want completed. AIRA-X will plan, execute, validate, and pause for approval when actions are risky."}
              </p>
            </div>
          )}

          {turns.map((turn, index) => (
            <div key={`${turn.question}-${index}`} className="fade-up space-y-4">
              <div className="ml-auto max-w-2xl rounded-[1.25rem] rounded-tr-md bg-[var(--accent)] px-5 py-3 text-sm font-semibold leading-6 text-[var(--accent-foreground)] shadow-[var(--shadow-soft)]">
                {turn.question}
              </div>

              {turn.error && (
                <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
                  {turn.error}
                </div>
              )}

              {turn.response && (
                <div className="sarvam-card rounded-[1.5rem] p-5">
                  <div className="mb-3 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
                    <div className="rounded-xl border border-[var(--border)] bg-[var(--accent-soft)] p-2 text-[var(--accent)]">
                      <Sparkles className="h-4 w-4" />
                    </div>
                    AI Answer
                  </div>

                  <div className="whitespace-pre-wrap text-sm leading-7 text-[var(--text)]">
                    {cleanAnswer(turn.response.answer)}
                  </div>

                  {turn.response.citations.length > 0 && (
                    <div className="mt-5 rounded-[1.25rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                      <p className="mb-3 text-sm font-semibold text-[var(--text-strong)]">
                        Sources
                      </p>

                      <CitationList citations={turn.response.citations} />
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="fade-up w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
              Researching sources...
            </div>
          )}

          {airaXLoading && (
            <div className="fade-up w-fit rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-5 py-3 text-sm font-medium text-[var(--accent)] shadow-[var(--shadow-soft)]">
              Running AIRA-X workflow...
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <div className="sarvam-card rounded-[1.5rem] p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
              <FileUp className="h-4 w-4 text-[var(--accent)]" />
              Document Intake
            </div>

            <label className="group flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-5 text-center transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]">
              <input
                type="file"
                multiple
                onChange={handleUploadDocuments}
                disabled={uploadLoading}
                className="hidden"
              />

              <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
                <UploadCloud className="h-5 w-5" />
              </div>

              <p className="text-sm font-bold text-[var(--text-strong)]">
                {uploadLoading ? "Uploading..." : "Upload documents"}
              </p>

              <p className="mt-1 max-w-xs text-xs leading-5 text-[var(--text-muted)]">
                Add PDFs or source files to the knowledge layer, then ask AIRA
                questions against them.
              </p>
            </label>

            {uploadMessage && (
              <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-3 text-xs font-semibold text-[var(--success)]">
                {uploadMessage}
              </div>
            )}

            {uploadError && (
              <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-3 text-xs font-semibold text-[var(--danger)]">
                {uploadError}
              </div>
            )}
          </div>

          {airaXResponse && (
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
                <Activity className="h-4 w-4 text-[var(--accent)]" />
                Workflow Result
              </div>

              <div className="space-y-2 text-sm text-[var(--text)]">
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
                <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-xl border border-[color-mix(in_srgb,var(--warning)_30%,transparent)] bg-[var(--surface-soft)] p-2 text-[var(--warning)]">
                      <ShieldCheck className="h-5 w-5" />
                    </div>

                    <div className="flex-1">
                      <h3 className="text-sm font-bold text-[var(--warning)]">
                        Approval Required
                      </h3>

                      <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
                        AIRA-X paused because this action can modify your
                        environment and needs permission before continuing.
                      </p>

                      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-sm text-[var(--text)]">
                        <strong>Pending action:</strong>{" "}
                        {airaXResponse.pending_action || "Unknown action"}
                      </div>

                      {renderApprovalContext(airaXResponse.approval_context)}

                      <div className="mt-4 flex flex-wrap gap-3">
                        <button
                          type="button"
                          onClick={handleApproveAiraX}
                          disabled={approvalLoading || rejectionLoading}
                          className="rounded-xl bg-[var(--warning)] px-5 py-3 text-sm font-bold text-white shadow-[var(--shadow-soft)] transition disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {approvalLoading
                            ? "Approving and continuing..."
                            : "Approve & Continue"}
                        </button>

                        <button
                          type="button"
                          onClick={handleRejectAiraX}
                          disabled={approvalLoading || rejectionLoading}
                          className="inline-flex items-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-bold text-[var(--danger)] shadow-[var(--shadow-soft)] transition hover:bg-[var(--danger-soft)] disabled:cursor-not-allowed disabled:opacity-60"
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
            </div>
          )}

          {airaXResponse && (
            <>
              <div className="sarvam-card rounded-[1.5rem] p-5">
                <div className="mb-4 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
                  <GitBranch className="h-4 w-4 text-[var(--accent)]" />
                  Execution Plan
                </div>

                <div className="space-y-3">
                  {airaXResponse.plan.map((step) => (
                    <div
                      key={step.id}
                      className={cn(
                        "rounded-2xl border p-4 text-sm",
                        step.status === "failed" ||
                          step.status === "blocked" ||
                          step.status === "rejected"
                          ? "border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)]"
                          : "border-[var(--border)] bg-[var(--surface-soft)]"
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <p className="font-semibold text-[var(--text-strong)]">
                          {step.id}. {step.title}
                        </p>

                        <span
                          className={cn(
                            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold",
                            getWorkflowStatusClass(step.status)
                          )}
                        >
                          {step.status}
                        </span>
                      </div>

                      <p className="mt-1 text-[var(--text-muted)]">
                        {step.description}
                      </p>

                      <div className="mt-2 grid gap-1 text-xs text-[var(--text-muted)] sm:grid-cols-2">
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
                        <p className="mb-2 text-xs font-semibold text-[var(--text-muted)]">
                          Result
                        </p>

                        {step.result ? (
                          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-xl p-4 text-xs leading-6">
                            {step.result}
                          </pre>
                        ) : (
                          <p className="text-xs text-[var(--text-subtle)]">
                            No result yet
                          </p>
                        )}
                      </div>

                      {step.error && (
                        <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] p-3 text-xs text-[var(--danger)]">
                          <strong>Error:</strong> {step.error}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {airaXResponse.workflow_logs &&
                airaXResponse.workflow_logs.length > 0 && (
                  <div className="sarvam-card rounded-[1.5rem] p-5">
                    <div className="mb-4 flex items-center gap-2 text-sm font-bold text-[var(--text-strong)]">
                      <History className="h-4 w-4 text-[var(--secondary)]" />
                      Workflow Logs
                    </div>

                    <div className="space-y-3">
                      {airaXResponse.workflow_logs.map((log, index) => (
                        <div
                          key={`${log.timestamp}-${index}`}
                          className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-xs text-[var(--text)]"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="font-semibold text-[var(--text-strong)]">
                              {log.agent}
                            </p>

                            <p className="text-[var(--text-subtle)]">
                              {new Date(log.timestamp).toLocaleString()}
                            </p>
                          </div>

                          <p className="mt-1">
                            <strong>Event:</strong> {log.event}
                          </p>

                          <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-xs leading-5 text-[var(--text-muted)]">
                            {renderLogMessage(log)}

                            {!knownLogEvents.includes(log.event) && (
                              <pre className="mt-2 overflow-auto rounded-lg p-3 text-[11px] leading-5">
                                {JSON.stringify(log.details, null, 2)}
                              </pre>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
            </>
          )}
        </aside>
      </div>

      <form
        onSubmit={submit}
        className="sticky bottom-4 rounded-[1.75rem] border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)] backdrop-blur-xl"
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={
            isAiraMode
              ? "Ask AIRA a research question..."
              : "Ask a question or give AIRA-X a task..."
          }
          className="h-24 w-full resize-none rounded-[1.15rem] border border-[var(--border)] bg-[var(--surface-strong)] p-4 text-sm text-[var(--text-strong)] caret-[var(--accent)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
        />

        <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <label className="flex w-fit cursor-pointer items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--text-muted)]">
            <input
              type="checkbox"
              checked={forceWeb}
              onChange={(event) => setForceWeb(event.target.checked)}
              className="accent-[var(--accent)]"
            />

            <Globe2 className="h-4 w-4 text-[var(--accent)]" />
            Include web search
          </label>

          <div className="flex flex-wrap items-center gap-2">
            {!isAiraMode && (
              <button
                type="button"
                onClick={handleRunAiraX}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--secondary)] px-5 py-2.5 text-sm font-bold text-white shadow-[var(--shadow-soft)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Workflow className="h-4 w-4" />
                {airaXLoading ? "Running..." : "Run AIRA-X"}
              </button>
            )}

            <button
              disabled={busy}
              className="group inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-5 py-2.5 text-sm font-bold text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Send className="h-4 w-4 transition-all duration-500 ease-out group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:rotate-12" />
              {isAiraMode ? "Ask AIRA" : "Send"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
