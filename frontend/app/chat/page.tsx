"use client";

import {
  useEffect,
  useMemo,
  useRef,
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
  FileUp,
  GitBranch,
  Globe2,
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
import { AssistantAnswerContent } from "@/components/assistant-answer";
import { CitationList } from "@/components/citation-list";
import {
  TechnicalDetailRow,
  TechnicalDetailsGrid,
  TechnicalDetailsPanel,
} from "@/components/technical-details";
import {
  type AssistantRunResponse,
  type ChatResponse,
  approveAiraX,
  assistantWorkflowToAiraXRun,
  isMultiTaskResponse,
  rejectAiraX,
  runAssistant,
  uploadDocuments,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Turn = {
  question: string;
  response?: ChatResponse | AssistantRunResponse;
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
          "mt-1 whitespace-pre-wrap break-words text-sm font-semibold text-[var(--text-strong)]",
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
    <TechnicalDetailsPanel summary="Cleanup trace">
      <div className="space-y-3">
        {cleanupActions.map((cleanup: any, index: number) => (
          <div
            key={`${cleanup.tool_action}-${index}`}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-xs text-[var(--text)]"
          >
            <p>
              <strong>Reason:</strong> {cleanup.reason}
            </p>

            <p className="mt-1">
              <strong>Status:</strong>{" "}
              {cleanup.result?.success ? "successful" : "failed"}
            </p>

            <p className="mt-1">
              <strong>Tool action:</strong> {cleanup.tool_name}:
              {cleanup.tool_action}
            </p>

            {cleanup.result?.command && (
              <p className="mt-1">
                <strong>Command:</strong> {cleanup.result.command}
              </p>
            )}
          </div>
        ))}
      </div>
    </TechnicalDetailsPanel>
  );
}

function AssistantTurnTechnicalDetails({
  response,
}: {
  response: AssistantRunResponse;
}) {
  const workflow = response.workflow;
  const rows: Array<{ label: string; value: string; mono?: boolean }> = [];

  if (response.run_id) {
    rows.push({ label: "Run ID", value: response.run_id, mono: true });
  }

  if (workflow?.decision) {
    rows.push({ label: "Decision", value: String(workflow.decision) });
  }

  if (response.metadata?.tool_name) {
    rows.push({
      label: "Tool",
      value: `${response.metadata.tool_name}:${response.metadata.tool_action || "action"}`,
      mono: true,
    });
  }

  if (Array.isArray(response.metadata?.response_types)) {
    rows.push({
      label: "Task routes",
      value: response.metadata.response_types.join(", "),
    });
  }

  if (rows.length === 0) {
    return null;
  }

  return (
    <TechnicalDetailsPanel className="mt-4">
      <TechnicalDetailsGrid>
        {rows.map((row) => (
          <TechnicalDetailRow
            key={row.label}
            label={row.label}
            value={row.value}
            mono={row.mono}
          />
        ))}
      </TechnicalDetailsGrid>
    </TechnicalDetailsPanel>
  );
}

function collectWorkflowTechnicalRows(response: AiraXResponse) {
  const rows: Array<{ label: string; value: string; mono?: boolean }> = [
    { label: "Status", value: response.status || "unknown" },
    { label: "Decision", value: response.decision || "unknown" },
  ];

  if (response.run_id) {
    rows.push({ label: "Run ID", value: response.run_id, mono: true });
  }

  const agents = [
    ...new Set(
      (response.plan || [])
        .map((step) => step.assigned_agent)
        .filter(Boolean)
    ),
  ];

  if (agents.length > 0) {
    rows.push({ label: "Agents", value: agents.join(", ") });
  }

  const toolActions = [
    ...new Set(
      (response.plan || [])
        .filter((step) => step.tool_name && step.tool_action)
        .map((step) => `${step.tool_name}:${step.tool_action}`)
    ),
  ];

  if (toolActions.length > 0) {
    rows.push({
      label: "Tool actions",
      value: toolActions.join(" · "),
      mono: true,
    });
  }

  return rows;
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

function getAssistantResponse(
  response?: ChatResponse | AssistantRunResponse
): AssistantRunResponse | null {
  if (response && "response_type" in response) {
    return response;
  }

  return null;
}

function ResearchTurnCard({ turn }: { turn: Turn }) {
  const assistantResponse = getAssistantResponse(turn.response);
  const multiTask =
    assistantResponse && isMultiTaskResponse(assistantResponse)
      ? assistantResponse
      : null;
  const taskCount = multiTask?.metadata?.task_count ?? 0;
  const failedTasks = multiTask?.metadata?.failed_tasks ?? [];
  const completedTasks =
    taskCount > 0 ? Math.max(taskCount - failedTasks.length, 0) : 0;

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
            icon={
              multiTask ? (
                <Workflow className="h-4 w-4" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )
            }
            title={multiTask ? "Multi-task results" : "AIRA-X Answer"}
            description={
              multiTask && taskCount > 0
                ? failedTasks.length > 0
                  ? `Ran ${taskCount} tasks — ${completedTasks} completed, ${failedTasks.length} failed.`
                  : `Ran ${taskCount} tasks successfully, one by one.`
                : undefined
            }
          />

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-5">
            <AssistantAnswerContent answer={turn.response.answer} />
          </div>

          {turn.response.citations.length > 0 && (
            <div className="mt-5 rounded-[1.25rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="mb-3 text-sm font-black text-[var(--text-strong)]">
                Sources
              </p>

              <CitationList citations={turn.response.citations} />
            </div>
          )}

          {assistantResponse &&
            (assistantResponse.run_id ||
              assistantResponse.workflow?.decision ||
              assistantResponse.metadata?.tool_name ||
              Array.isArray(assistantResponse.metadata?.response_types)) && (
              <AssistantTurnTechnicalDetails response={assistantResponse} />
            )}
        </div>
      )}
    </div>
  );
}

function AssistantWorkspaceLinks({
  onUploadClick,
}: {
  onUploadClick: () => void;
}) {
  return (
    <div className="pro-link-row mt-8">
      <Link href="/documents" className="pro-link-pill">
        <Library className="h-3.5 w-3.5" />
        Knowledge
      </Link>
      <Link href="/workflows" className="pro-link-pill">
        <Workflow className="h-3.5 w-3.5" />
        Workflows
      </Link>
      <Link href="/approvals" className="pro-link-pill">
        <ShieldCheck className="h-3.5 w-3.5" />
        Approvals
      </Link>
      <Link href="/history" className="pro-link-pill">
        <Database className="h-3.5 w-3.5" />
        History
      </Link>
      <button type="button" onClick={onUploadClick} className="pro-link-pill">
        <FileUp className="h-3.5 w-3.5" />
        Upload documents
      </button>
      <span className="pro-link-pill cursor-default opacity-90">
        <Globe2 className="h-3.5 w-3.5" />
        Web search on
      </span>
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
      className="pro-quick-action inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-bold"
    >
      <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
      {label}
    </button>
  );
}

function AiraHomeStage({
  question,
  setQuestion,
  busy,
  loading,
  onSubmit,
  onComposerFocus,
}: {
  question: string;
  setQuestion: (value: string) => void;
  busy: boolean;
  loading: boolean;
  onSubmit: (event: FormEvent) => Promise<void>;
  onComposerFocus: () => void;
}) {
  return (
    <section className="assistant-empty-shell w-full">
      <div className="w-full max-w-3xl text-center">
        <p className="pro-kicker mx-auto mb-4 w-fit px-3 py-1.5">
          <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
          AIRA-X Assistant
        </p>

        <h2 className="text-3xl font-black tracking-tight text-[var(--text-strong)] md:text-4xl md:leading-tight">
          How can I help you today?
        </h2>

        <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-[var(--text-muted)]">
          Ask a question, analyze documents, run a workflow, or inspect a
          previous execution. Routing is handled automatically.
        </p>

        <form
          onSubmit={onSubmit}
          className="pro-composer mx-auto mt-8 w-full rounded-[1.5rem] p-3 text-left"
        >
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onFocus={onComposerFocus}
            placeholder="Message AIRA-X..."
            className="min-h-[88px] w-full resize-none rounded-[1rem] border border-transparent bg-transparent p-4 text-sm text-[var(--text-strong)] caret-[var(--accent)] outline-none placeholder:text-[var(--text-subtle)]"
          />

          <div className="mt-2 flex items-center justify-between border-t border-[var(--border)] px-1 pb-1 pt-3">
            {/* Web search always-on indicator */}
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-semibold text-[var(--text-muted)]">
              <Globe2 className="h-3.5 w-3.5 text-[var(--accent)]" />
              Web search on
            </div>

            <button
              disabled={busy || !question.trim()}
              className="pro-send inline-flex items-center justify-center gap-2 rounded-full bg-[var(--accent)] px-5 py-2.5 text-sm font-bold text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {loading ? "Working..." : "Send"}
            </button>
          </div>
        </form>

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <SuggestionChip
            label="Explain a topic"
            prompt="Explain "
            onSelect={setQuestion}
          />
          <SuggestionChip
            label="Run Python"
            prompt='run python code: print("Hello from AIRA-X")'
            onSelect={setQuestion}
          />
          <SuggestionChip
            label="Git status"
            prompt="git status"
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
  const isCompleted = response.status === "completed";
  const isFailed =
    response.status === "failed" ||
    response.status === "rejected" ||
    response.status === "blocked";
  const finalAnswer = response.final_answer || "No final answer yet.";

  return (
    <div className="sarvam-card rounded-[1.75rem] p-5">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border",
              isCompleted
                ? "border-[color-mix(in_srgb,var(--success)_36%,transparent)] bg-[var(--success-soft)] text-[var(--success)]"
                : isFailed
                  ? "border-[color-mix(in_srgb,var(--danger)_36%,transparent)] bg-[var(--danger-soft)] text-[var(--danger)]"
                  : "border-[color-mix(in_srgb,var(--warning)_36%,transparent)] bg-[var(--warning-soft)] text-[var(--warning)]"
            )}
          >
            {isCompleted ? (
              <CheckCircle2 className="h-5 w-5" />
            ) : isFailed ? (
              <XCircle className="h-5 w-5" />
            ) : (
              <Activity className="h-5 w-5" />
            )}
          </div>

          <div>
            <div
              className={cn(
                "mb-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-black uppercase tracking-wide",
                getWorkflowStatusClass(response.status)
              )}
            >
              {response.status || "unknown"}
            </div>

            <h2 className="text-xl font-black tracking-tight text-[var(--text-strong)]">
              {isCompleted
                ? "Execution completed"
                : isFailed
                  ? "Execution stopped"
                  : "Execution in progress"}
            </h2>

            <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
              AIRA-X completed the workflow and prepared the result below.
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-[1.4rem] border border-[var(--border-strong)] bg-[var(--surface-soft)] p-5 shadow-[var(--shadow-soft)]">
        <p className="mb-3 text-xs font-black uppercase tracking-[0.18em] text-[var(--text-subtle)]">
          Final Answer
        </p>

        <AssistantAnswerContent answer={finalAnswer} />
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

      <TechnicalDetailsPanel className="mt-4">
        <TechnicalDetailsGrid>
          {collectWorkflowTechnicalRows(response).map((row) => (
            <TechnicalDetailRow
              key={row.label}
              label={row.label}
              value={row.value}
              mono={row.mono}
            />
          ))}
        </TechnicalDetailsGrid>
      </TechnicalDetailsPanel>

      <CleanupActions memory={response.memory} />
    </div>
  );
}

function ExecutionPlanCard({ steps }: { steps: AiraXStep[] }) {
  return (
    <TechnicalDetailsPanel
      className="sarvam-card rounded-[1.5rem] p-5"
      summary={`Execution plan (${steps.length} step${steps.length === 1 ? "" : "s"})`}
    >
      <PanelHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Execution Plan"
        description="Step-by-step trace for this workflow run."
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

            <div className="mt-3">
              <p className="mb-2 text-xs font-semibold text-[var(--text-muted)]">
                Result
              </p>

              {step.result ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                  <AssistantAnswerContent answer={step.result} />
                </div>
              ) : (
                <p className="text-xs text-[var(--text-subtle)]">
                  No result yet
                </p>
              )}
            </div>

            {(step.assigned_agent || step.tool_name || step.tool_action) && (
              <TechnicalDetailsPanel
                className="mt-3"
                summary="Step technical details"
              >
                <TechnicalDetailsGrid>
                  {step.assigned_agent && (
                    <TechnicalDetailRow
                      label="Agent"
                      value={step.assigned_agent}
                    />
                  )}
                  {step.tool_name && (
                    <TechnicalDetailRow label="Tool" value={step.tool_name} />
                  )}
                  {step.tool_action && (
                    <TechnicalDetailRow
                      label="Tool action"
                      value={step.tool_action}
                      mono
                    />
                  )}
                </TechnicalDetailsGrid>
              </TechnicalDetailsPanel>
            )}

            {step.error && (
              <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] p-3 text-xs text-[var(--danger)]">
                <strong>Error:</strong> {step.error}
              </div>
            )}
          </div>
        ))}
      </div>
    </TechnicalDetailsPanel>
  );
}

function FocusComposerOverlay({
  question,
  setQuestion,
  busy,
  loading,
  airaXLoading,
  onSubmit,
  onClose,
}: {
  question: string;
  setQuestion: (value: string) => void;
  busy: boolean;
  loading: boolean;
  airaXLoading: boolean;
  onSubmit: (event: FormEvent) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <>
      <button
        type="button"
        aria-label="Close focus composer"
        onClick={onClose}
        className="fixed inset-0 z-30 bg-black/35 backdrop-blur-md transition"
      />

      <form
        onSubmit={onSubmit}
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[min(820px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-[2rem] border border-[var(--border-strong)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)] backdrop-blur-2xl",
          "research-composer chatgpt-composer"
        )}
      >
        <div className="mb-3 flex items-center justify-between gap-3 px-1">
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)]">
            <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
            Focused prompt
          </div>

          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
            aria-label="Close composer focus mode"
          >
            <XCircle className="h-4 w-4" />
          </button>
        </div>

        <textarea
          autoFocus
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Message AIRA-X..."
          className="min-h-[150px] w-full resize-none rounded-[1rem] border border-[var(--border)] bg-[var(--surface-strong)] p-5 text-base leading-7 text-[var(--text-strong)] caret-[var(--accent)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
        />

        <div className="mt-3 flex items-center justify-between">
          {/* Web search always-on indicator */}
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--text-muted)]">
            <Globe2 className="h-4 w-4 text-[var(--accent)]" />
            Web search on
          </div>

          <button
            disabled={busy || !question.trim()}
            className="pro-send inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-bold shadow-[var(--shadow-soft)] disabled:cursor-not-allowed disabled:opacity-60 bg-[var(--accent)] text-[var(--accent-foreground)]"
          >
            {loading || airaXLoading ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            {loading || airaXLoading ? "Working..." : "Send"}
          </button>
        </div>

        <p className="mt-3 px-1 text-xs leading-5 text-[var(--text-subtle)]">
          Press Esc or click outside to exit focus mode.
        </p>
      </form>
    </>
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
  const [question, setQuestion] = useState("");
  const [composerFocused, setComposerFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [airaXLoading, setAiraXLoading] = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [rejectionLoading, setRejectionLoading] = useState(false);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [airaXResponse, setAiraXResponse] = useState<AiraXResponse | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    if (!composerFocused) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setComposerFocused(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [composerFocused]);

  async function handleUnifiedAssistant(event?: FormEvent) {
    event?.preventDefault();

    const trimmed = question.trim();
    if (!trimmed) return;

    setComposerFocused(false);
    setQuestion("");
    setLoading(true);
    setAiraXLoading(false);

    try {
      // Web search is always enabled — no user toggle needed
      const response = await runAssistant(trimmed, true);

      const shouldRenderAsWorkflow =
        !isMultiTaskResponse(response) &&
        (response.response_type === "execution_result" ||
          response.response_type === "approval_required");

      if (shouldRenderAsWorkflow) {
        const workflowRun = assistantWorkflowToAiraXRun(response.workflow);

        if (workflowRun) {
          setAiraXResponse(workflowRun);
          setTurns([]);
        } else {
          setAiraXResponse(null);
          setTurns((prev) => [...prev, { question: trimmed, response }]);
        }
      } else {
        setAiraXResponse(null);
        setTurns((prev) => [...prev, { question: trimmed, response }]);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "AIRA-X assistant failed.";

      setAiraXResponse(null);
      setTurns((prev) => [...prev, { question: trimmed, error: message }]);
    } finally {
      setLoading(false);
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
    await handleUnifiedAssistant(event);
  }

  return (
    <div
      className={cn(
        "mx-auto flex min-h-[calc(100vh-64px)] w-full flex-col gap-5",
        threadIsEmpty ? "max-w-5xl" : "max-w-6xl",
        "aira-chat-page"
      )}
    >
      <input
        ref={uploadInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleUploadDocuments}
      />

      {(uploadMessage || uploadError) && (
        <div
          className={cn(
            "rounded-2xl border px-4 py-3 text-sm font-semibold",
            uploadError
              ? "border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] text-[var(--danger)]"
              : "border-[color-mix(in_srgb,var(--success)_34%,transparent)] bg-[var(--success-soft)] text-[var(--success)]"
          )}
        >
          {uploadError || uploadMessage}
        </div>
      )}

      <div
        className="aira-focus-content flex flex-1 flex-col gap-5"
        data-composer-focused={composerFocused ? "true" : "false"}
      >
        {threadIsEmpty && !loading && !airaXLoading ? (
          <div className="flex flex-1 flex-col">
            <AiraHomeStage
              question={question}
              setQuestion={setQuestion}
              busy={busy}
              loading={loading}
              onSubmit={handleSubmit}
              onComposerFocus={() => setComposerFocused(true)}
            />

            <AssistantWorkspaceLinks
              onUploadClick={() => uploadInputRef.current?.click()}
            />
          </div>
        ) : (
          <div className="assistant-thread-shell flex flex-1 flex-col gap-5">
            <section className="aira-result-focus flex min-h-[260px] flex-col gap-4">
              {turns.map((turn, index) => (
                <ResearchTurnCard key={`${turn.question}-${index}`} turn={turn} />
              ))}

              {loading && (
                <div className="fade-up w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
                  Thinking through the best route...
                </div>
              )}

              {airaXLoading && (
                <div className="fade-up w-fit rounded-full border border-[var(--border-strong)] bg-[var(--secondary-soft)] px-5 py-3 text-sm font-medium text-[var(--secondary)] shadow-[var(--shadow-soft)]">
                  Running AIRA-X workflow...
                </div>
              )}

              {airaXResponse && (
                <>
                  <WorkflowResultCard
                    response={airaXResponse}
                    approvalLoading={approvalLoading}
                    rejectionLoading={rejectionLoading}
                    onApprove={handleApproveAiraX}
                    onReject={handleRejectAiraX}
                  />

                  <ExecutionPlanCard steps={airaXResponse.plan} />
                </>
              )}
            </section>
          </div>
        )}

        {!threadIsEmpty && (
          <form
            onSubmit={handleSubmit}
            className="pro-composer sticky bottom-4 rounded-[1.5rem] p-4"
          >
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onFocus={() => setComposerFocused(true)}
              placeholder="Message AIRA-X..."
              className="h-24 w-full resize-none rounded-[1rem] border border-[var(--border)] bg-[var(--surface-strong)] p-4 text-sm text-[var(--text-strong)] caret-[var(--accent)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
            />

            <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex flex-wrap gap-2">
                {/* Web search always-on indicator */}
                <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--text-muted)]">
                  <Globe2 className="h-4 w-4 text-[var(--accent)]" />
                  Web search on
                </div>

                <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-sm font-medium text-[var(--text-muted)]">
                  <ShieldAlert className="h-4 w-4 text-[var(--warning)]" />
                  Approval-gated execution when needed
                </div>
              </div>

              <button
                disabled={busy || !question.trim()}
                className={cn(
                  "group inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-black shadow-[var(--shadow-soft)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60",
                  "bg-[var(--accent)] text-[var(--accent-foreground)]"
                )}
              >
                {loading || airaXLoading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4 transition-all duration-500 ease-out group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:rotate-12" />
                )}
                {loading || airaXLoading ? "Working..." : "Send"}
              </button>
            </div>
          </form>
        )}
      </div>

      {composerFocused && (
        <FocusComposerOverlay
          question={question}
          setQuestion={setQuestion}
          busy={busy}
          loading={loading}
          airaXLoading={airaXLoading}
          onSubmit={handleSubmit}
          onClose={() => setComposerFocused(false)}
        />
      )}
    </div>
  );
}