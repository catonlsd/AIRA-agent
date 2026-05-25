"use client";

import {
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
  FileUp,
  GitBranch,
  Globe2,
  History,
  Library,
  RefreshCw,
  Send,
  ShieldAlert,
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

type AiraXStep = {
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

type AiraXResponse = {
  run_id?: string;
  status: string;
  decision: string;
  final_answer: string | null;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext | null;
  plan: AiraXStep[];
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

function cleanAnswer(answer: string) {
  return answer
    .replace(/^###\s?/gm, "")
    .replace(/^##\s?/gm, "")
    .replace(/^#\s?/gm, "")
    .replace(/\*\*/g, "")
    .replace(/Sources[\s\S]*/i, "")
    .trim();
}

function formatDateTime(value?: string) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function getWorkflowStatusClass(status?: string) {
  if (status === "completed" || status === "success") {
    return "status-success";
  }

  if (status === "failed" || status === "rejected" || status === "blocked") {
    return "status-danger";
  }

  if (
    status === "requires_approval" ||
    status === "retrying" ||
    status === "pending" ||
    status === "running"
  ) {
    return "status-warning";
  }

  return "status-info";
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
          AIRA-X unstaged Git changes after rejected approval. Cleanup status:{" "}
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

function InfoTile({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
        {label}
      </p>

      <p
        className={cn(
          "mt-1 break-words text-sm font-semibold text-[var(--text-strong)]",
          mono && "font-mono text-xs"
        )}
      >
        {value}
      </p>
    </div>
  );
}

function CodeBlock({
  value,
  fallback = "No data available.",
}: {
  value?: string;
  fallback?: string;
}) {
  return (
    <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-xl p-3 text-xs leading-5">
      {value?.trim() || fallback}
    </pre>
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

function PanelHeader({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div className="mb-4 flex items-start gap-3">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
        {icon}
      </div>

      <div>
        <h2 className="text-sm font-black text-[var(--text-strong)]">
          {title}
        </h2>

        {description && (
          <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

function GitWritePreflight({ context }: { context: ApprovalContext }) {
  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-4">
      <PanelHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Git Preflight Summary"
        description="Review repository changes before approving this Git write action."
      />

      <div className="grid gap-3 md:grid-cols-2">
        <InfoTile label="Current Branch" value={context.branch || "Unknown"} />
        <InfoTile
          label="Git Action"
          value={context.pending_action || "Unknown action"}
        />
      </div>

      {context.commit_message && (
        <div className="mt-3">
          <InfoTile label="Commit Message" value={context.commit_message} />
        </div>
      )}

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Changed Files
        </p>

        <CodeBlock
          value={context.changed_files}
          fallback="No changed files detected."
        />
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Diff Summary
        </p>

        <CodeBlock
          value={context.diff_summary}
          fallback="No diff summary available."
        />
      </div>
    </div>
  );
}

function GitPushPreflight({ context }: { context: ApprovalContext }) {
  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4">
      <PanelHeader
        icon={<UploadCloud className="h-4 w-4" />}
        title="Git Push Preflight Summary"
        description="Review remote target, tracking status, and recent commits before approving."
      />

      <div className="grid gap-3 md:grid-cols-2">
        <InfoTile label="Target Remote" value={context.target_remote || "origin"} />
        <InfoTile
          label="Target Branch"
          value={context.target_branch || context.branch || "Unknown branch"}
        />
        <InfoTile label="Current Branch" value={context.branch || "Unknown"} />
        <InfoTile
          label="Git Action"
          value={context.pending_action || "Unknown action"}
        />
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Branch Tracking Status
        </p>

        <CodeBlock
          value={context.status_branch}
          fallback="No branch tracking status available."
        />
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Remote Info
        </p>

        <CodeBlock
          value={context.remote_info}
          fallback="No remote info available."
        />
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Latest Local Commit
        </p>

        <CodeBlock
          value={context.last_commit}
          fallback="No latest commit available."
        />
      </div>

      <div className="mt-3">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Recent Local Commits
        </p>

        <CodeBlock
          value={context.recent_commits}
          fallback="No recent commits available."
        />
      </div>
    </div>
  );
}

function ApprovalContextPanel({ context }: { context?: ApprovalContext | null }) {
  if (!context) {
    return null;
  }

  if (context.type === "git_write_preflight") {
    return <GitWritePreflight context={context} />;
  }

  if (context.type === "git_push_preflight") {
    return <GitPushPreflight context={context} />;
  }

  return null;
}

function CleanupActions({ memory }: { memory: any }) {
  const cleanupActions = memory?.cleanup_actions || [];

  if (!Array.isArray(cleanupActions) || cleanupActions.length === 0) {
    return null;
  }

  return (
    <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] p-5">
      <PanelHeader
        icon={<CheckCircle2 className="h-4 w-4" />}
        title="Cleanup Actions"
        description="AIRA-X performed cleanup after rejection or stop conditions."
      />

      <div className="space-y-3">
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

function EmptyExecutionState() {
  return (
    <div className="aira-console fade-up flex min-h-[340px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--secondary-soft)] text-[var(--secondary)]">
        <Workflow className="h-5 w-5" />
      </div>

      <h2 className="text-xl font-black text-[var(--text-strong)]">
        Ready to execute a workflow
      </h2>

      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
        Describe the task you want completed. AIRA-X will plan, execute,
        validate, and pause for approval when actions are risky.
      </p>

      <div className="mt-5 grid w-full max-w-xl gap-2 sm:grid-cols-3">
        <InfoTile label="Plan" value="Agent-generated steps" />
        <InfoTile label="Guard" value="Approval gates" />
        <InfoTile label="Trace" value="Logs + outputs" />
      </div>
    </div>
  );
}

function ResearchTurnCard({ turn }: { turn: Turn }) {
  const confidence = (turn.response as any)?.confidence || "not recorded";

  return (
    <div className="fade-up space-y-4">
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
          <PanelHeader
            icon={<Sparkles className="h-4 w-4" />}
            title="AIRA Answer"
            description={`Confidence: ${confidence}`}
          />

          <div className="whitespace-pre-wrap rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-5 text-sm leading-7 text-[var(--text)]">
            {cleanAnswer(turn.response.answer)}
          </div>

          {turn.response.citations.length > 0 && (
            <div className="mt-5 rounded-[1.25rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-3 text-sm font-black text-[var(--text-strong)]">
                Sources
              </p>

              <CitationList citations={turn.response.citations} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DocumentIntakeCard({
  uploadLoading,
  uploadMessage,
  uploadError,
  onUpload,
}: {
  uploadLoading: boolean;
  uploadMessage: string;
  uploadError: string;
  onUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
}) {
  return (
    <div className="sarvam-card rounded-[1.5rem] p-5">
      <PanelHeader
        icon={<FileUp className="h-4 w-4" />}
        title="Document Intake"
        description="Upload sources once, then ask AIRA against your indexed knowledge layer."
      />

      <label className="group flex min-h-[360px] cursor-pointer flex-col items-center justify-center rounded-[1.75rem] border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-8 text-center transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]">
        <input
          type="file"
          multiple
          onChange={onUpload}
          disabled={uploadLoading}
          className="hidden"
        />

        <div className="mb-6 flex h-24 w-24 items-center justify-center rounded-[1.8rem] border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)] shadow-[var(--shadow-soft)] transition group-hover:-translate-y-1 group-hover:scale-105">
          {uploadLoading ? (
            <RefreshCw className="h-9 w-9 animate-spin" />
          ) : (
            <UploadCloud className="h-9 w-9" />
          )}
        </div>

        <p className="text-xl font-black text-[var(--text-strong)]">
          {uploadLoading ? "Indexing sources..." : "Upload documents"}
        </p>

        <p className="mt-2 max-w-xs text-sm leading-6 text-[var(--text-muted)]">
          Add PDFs or source files. AIRA turns them into retrievable context for
          summaries, citations, and grounded answers.
        </p>

        <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)]">
          <FileText className="h-3.5 w-3.5" />
          Select multiple files
        </div>
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
  );
}

function ResearchModeCard({ forceWeb }: { forceWeb: boolean }) {
  return (
    <div className="aira-panel rounded-[1.5rem] p-4">
      <PanelHeader
        icon={<Database className="h-4 w-4" />}
        title="Knowledge Context"
        description="Compact retrieval status and source-library access."
      />

      <div className="grid gap-3">
        <InfoTile
          label="Mode"
          value={forceWeb ? "Documents + Web" : "Document-first"}
        />
        <InfoTile label="Output" value="Answer + citations" />
      </div>

      <Link
        href="/documents"
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
      >
        <Library className="h-4 w-4" />
        Open Knowledge Base
        <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function SuggestionChip({
  label,
  prompt,
  onSelect,
}: {
  label: string;
  prompt: string;
  onSelect: (value: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(prompt)}
      className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:-translate-y-0.5 hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
    >
      <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
      {label}
    </button>
  );
}

function AiraHomeStage({
  question,
  setQuestion,
  forceWeb,
  setForceWeb,
  busy,
  loading,
  onSubmit,
}: {
  question: string;
  setQuestion: (value: string) => void;
  forceWeb: boolean;
  setForceWeb: (value: boolean) => void;
  busy: boolean;
  loading: boolean;
  onSubmit: (event: FormEvent) => Promise<void>;
}) {
  return (
    <section className="flex min-h-[560px] flex-col items-center justify-center rounded-[2rem] p-4 lg:min-h-[620px]">
      <div className="w-full max-w-3xl text-center">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)] shadow-[var(--shadow-soft)]">
          <Sparkles className="h-5 w-5" />
        </div>

        <h2 className="text-3xl font-black tracking-tight text-[var(--text-strong)] md:text-4xl">
          What should we research today?
        </h2>

        <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[var(--text-muted)]">
          Ask AIRA a focused question. It will search your uploaded knowledge
          base first and return a source-backed answer.
        </p>

        <form
          onSubmit={onSubmit}
          className="research-composer chatgpt-composer mx-auto mt-8 rounded-[2rem] border border-[var(--border)] bg-[var(--surface)] p-3 text-left shadow-[var(--shadow-card)] backdrop-blur-xl"
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask anything from your documents..."
            className="min-h-[82px] w-full resize-none rounded-[1.4rem] border border-transparent bg-[var(--surface-strong)] p-4 text-sm text-[var(--text-strong)] caret-[var(--accent)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)]"
          />

          <div className="mt-2 flex flex-col gap-3 px-1 pb-1 md:flex-row md:items-center md:justify-between">
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

            <button
              disabled={busy || !question.trim()}
              className="group inline-flex items-center justify-center gap-2 rounded-full bg-[var(--accent)] px-5 py-2.5 text-sm font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4 transition-all duration-500 ease-out group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:rotate-12" />
              )}
              {loading ? "Researching..." : "Ask AIRA"}
            </button>
          </div>
        </form>

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <SuggestionChip
            label="Summarize uploaded sources"
            prompt="Summarize the documents I uploaded and highlight the key points."
            onSelect={setQuestion}
          />
          <SuggestionChip
            label="Find cited answer"
            prompt="Answer this using my knowledge base and include citations: "
            onSelect={setQuestion}
          />
          <SuggestionChip
            label="Compare sources"
            prompt="Compare the relevant uploaded documents and explain the differences."
            onSelect={setQuestion}
          />
        </div>
      </div>
    </section>
  );
}

function WorkflowResultCard({
  response,
  approvalLoading,
  rejectionLoading,
  onApprove,
  onReject,
}: {
  response: AiraXResponse;
  approvalLoading: boolean;
  rejectionLoading: boolean;
  onApprove: () => Promise<void>;
  onReject: () => Promise<void>;
}) {
  return (
    <div className="sarvam-card rounded-[1.5rem] p-5">
      <PanelHeader
        icon={<Activity className="h-4 w-4" />}
        title="Workflow Result"
        description="Latest workflow status, decision, and approval state."
      />

      <div className="grid gap-3">
        <InfoTile label="Status" value={response.status} />
        <InfoTile label="Decision" value={response.decision} />
        <InfoTile
          label="Final Answer"
          value={response.final_answer || "No final answer yet"}
        />
        {response.run_id && (
          <InfoTile label="Run ID" value={response.run_id} mono />
        )}
      </div>

      {response.requires_approval && (
        <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-5">
          <PanelHeader
            icon={<ShieldCheck className="h-4 w-4" />}
            title="Approval Required"
            description="This action can modify your environment and needs permission before continuing."
          />

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-sm text-[var(--text)]">
            <strong>Pending action:</strong>{" "}
            {response.pending_action || "Unknown action"}
          </div>

          <ApprovalContextPanel context={response.approval_context} />

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={onApprove}
              disabled={approvalLoading || rejectionLoading}
              className="rounded-xl bg-[var(--warning)] px-5 py-3 text-sm font-black text-white shadow-[var(--shadow-soft)] transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              {approvalLoading
                ? "Approving and continuing..."
                : "Approve & Continue"}
            </button>

            <button
              type="button"
              onClick={onReject}
              disabled={approvalLoading || rejectionLoading}
              className="inline-flex items-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-black text-[var(--danger)] shadow-[var(--shadow-soft)] transition hover:bg-[var(--danger-soft)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <XCircle className="h-4 w-4" />
              {rejectionLoading ? "Rejecting..." : "Reject Action"}
            </button>
          </div>
        </div>
      )}

      <CleanupActions memory={response.memory} />
    </div>
  );
}

function ExecutionPlanCard({ steps }: { steps: AiraXStep[] }) {
  return (
    <div className="sarvam-card rounded-[1.5rem] p-5">
      <PanelHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Execution Plan"
        description={`${steps.length} planned execution step${
          steps.length === 1 ? "" : "s"
        }.`}
      />

      <div className="space-y-3">
        {steps.map((step) => (
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

              <RunBadge className={getWorkflowStatusClass(step.status)}>
                {step.status}
              </RunBadge>
            </div>

            <p className="mt-1 text-[var(--text-muted)]">{step.description}</p>

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
  );
}

function WorkflowLogsCard({ logs }: { logs?: WorkflowLog[] }) {
  if (!logs || logs.length === 0) {
    return null;
  }

  return (
    <div className="sarvam-card rounded-[1.5rem] p-5">
      <PanelHeader
        icon={<History className="h-4 w-4" />}
        title="Workflow Logs"
        description="Agent events and workflow trace entries."
      />

      <div className="space-y-3">
        {logs.map((log, index) => (
          <div
            key={`${log.timestamp}-${index}`}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-xs text-[var(--text)]"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold text-[var(--text-strong)]">
                {log.agent}
              </p>

              <p className="text-[var(--text-subtle)]">
                {formatDateTime(log.timestamp)}
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
  );
}

function ExecutionGuideCard() {
  return (
    <div className="aira-console rounded-[1.5rem] p-5">
      <PanelHeader
        icon={<Workflow className="h-4 w-4" />}
        title="Execution Guide"
        description="Use AIRA-X when the goal is to complete an action, not only answer a question."
      />

      <div className="space-y-3">
        <InfoTile label="1. Plan" value="Break the task into execution steps." />
        <InfoTile
          label="2. Execute"
          value="Call approved tools and record outputs."
        />
        <InfoTile
          label="3. Validate"
          value="Check the result and retry when useful."
        />
        <InfoTile
          label="4. Approve"
          value="Pause for user permission before risky actions."
        />
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

  const threadIsEmpty = useMemo(
    () => turns.length === 0 && !airaXResponse,
    [turns.length, airaXResponse]
  );

  async function submitAiraQuestion(event?: FormEvent) {
    event?.preventDefault();

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

  async function handleRunAiraX(event?: FormEvent) {
    event?.preventDefault();

    const trimmed = question.trim();
    if (!trimmed) return;

    setAiraXLoading(true);
    setAiraXResponse(null);

    try {
      const result = await runAiraX(trimmed);
      setAiraXResponse(result);
      setQuestion("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "AIRA-X workflow failed.";

      setAiraXResponse({
        status: "failed",
        decision: "error",
        final_answer: message,
        plan: [],
        execution_outputs: [],
        memory: {},
      });
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

  async function handleSubmit(event: FormEvent) {
    if (isAiraMode) {
      await submitAiraQuestion(event);
      return;
    }

    await handleRunAiraX(event);
  }

  return (
    <div
      className={cn(
        "mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-5",
        isAiraMode ? "aira-chat-page" : "airax-execution-page"
      )}
    >
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
              {isAiraMode ? (
                <Sparkles className="h-3.5 w-3.5" />
              ) : (
                <Workflow className="h-3.5 w-3.5" />
              )}
              {isAiraMode ? "Research workspace" : "Execute workspace"}
            </div>

            <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
              {isAiraMode ? "Ask AIRA" : "Execution Panel"}
            </h1>

            <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              {isAiraMode
                ? "Ask document-backed research questions, upload knowledge, and get grounded answers with citations."
                : "Give AIRA-X a task and inspect workflow results, approval checkpoints, execution plans, and logs."}
            </p>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4 lg:w-64">
            <p className="text-[11px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
              Active Mode
            </p>

            <p className="mt-1 text-sm font-black text-[var(--text-strong)]">
              {isAiraMode
                ? forceWeb
                  ? "Documents + Web"
                  : "Document-first"
                : "Workflow execution"}
            </p>

            <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
              {isAiraMode
                ? "Supplement the document context with web search whenever necessary."
                : "Risky actions pause for approval before execution."}
            </p>
          </div>
        </div>
      </section>

      {isAiraMode && threadIsEmpty ? (
        <div className="grid flex-1 gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
          <AiraHomeStage
            question={question}
            setQuestion={setQuestion}
            forceWeb={forceWeb}
            setForceWeb={setForceWeb}
            busy={busy}
            loading={loading}
            onSubmit={handleSubmit}
          />

          <aside className="space-y-4">
            <DocumentIntakeCard
              uploadLoading={uploadLoading}
              uploadMessage={uploadMessage}
              uploadError={uploadError}
              onUpload={handleUploadDocuments}
            />

            <ResearchModeCard forceWeb={forceWeb} />
          </aside>
        </div>
      ) : (
        <div
          className={cn(
            "grid flex-1 gap-5",
            isAiraMode
              ? "xl:grid-cols-[minmax(0,1fr)_430px]"
              : "xl:grid-cols-[minmax(0,1fr)_440px]"
          )}
        >
          <section className="flex min-h-[520px] flex-col gap-4">
            {threadIsEmpty && !isAiraMode && <EmptyExecutionState />}

            {turns.map((turn, index) => (
              <ResearchTurnCard key={`${turn.question}-${index}`} turn={turn} />
            ))}

            {loading && (
              <div className="fade-up w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
                Researching sources...
              </div>
            )}

            {airaXLoading && (
              <div className="fade-up w-fit rounded-full border border-[var(--border-strong)] bg-[var(--secondary-soft)] px-5 py-3 text-sm font-medium text-[var(--secondary)] shadow-[var(--shadow-soft)]">
                Running AIRA-X workflow...
              </div>
            )}
          </section>

          <aside className="space-y-4">
            {isAiraMode ? (
              <>
                <DocumentIntakeCard
                  uploadLoading={uploadLoading}
                  uploadMessage={uploadMessage}
                  uploadError={uploadError}
                  onUpload={handleUploadDocuments}
                />

                <ResearchModeCard forceWeb={forceWeb} />
              </>
            ) : (
              <>
                {airaXResponse ? (
                  <>
                    <WorkflowResultCard
                      response={airaXResponse}
                      approvalLoading={approvalLoading}
                      rejectionLoading={rejectionLoading}
                      onApprove={handleApproveAiraX}
                      onReject={handleRejectAiraX}
                    />

                    <ExecutionPlanCard steps={airaXResponse.plan} />

                    <WorkflowLogsCard logs={airaXResponse.workflow_logs} />
                  </>
                ) : (
                  <ExecutionGuideCard />
                )}
              </>
            )}
          </aside>
        </div>
      )}

      {!(isAiraMode && threadIsEmpty) && (
        <form
          onSubmit={handleSubmit}
          className={cn(
            "sticky bottom-4 rounded-[1.75rem] border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)] backdrop-blur-xl",
            isAiraMode ? "research-composer chatgpt-composer" : "aira-console"
          )}
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              isAiraMode
                ? "Ask AIRA a research question..."
                : "Tell AIRA-X what task to execute..."
            }
            className="h-24 w-full resize-none rounded-[1.15rem] border border-[var(--border)] bg-[var(--surface-strong)] p-4 text-sm text-[var(--text-strong)] caret-[var(--accent)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
          />

          <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            {isAiraMode ? (
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
            ) : (
              <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--text-muted)]">
                <ShieldAlert className="h-4 w-4 text-[var(--warning)]" />
                Approval-gated execution
              </div>
            )}

            <button
              disabled={busy || !question.trim()}
              className={cn(
                "group inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-black shadow-[var(--shadow-soft)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60",
                isAiraMode
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                  : "bg-[var(--secondary)] text-white"
              )}
            >
              {isAiraMode ? (
                loading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4 transition-all duration-500 ease-out group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:rotate-12" />
                )
              ) : airaXLoading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Workflow className="h-4 w-4" />
              )}

              {isAiraMode
                ? loading
                  ? "Asking..."
                  : "Ask AIRA"
                : airaXLoading
                  ? "Running..."
                  : "Run AIRA-X"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
