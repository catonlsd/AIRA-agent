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
  CheckCircle2,
  Database,
  FileUp,
  GitBranch,
  Library,
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
  streamAiraX,
  uploadDocuments,
  type Citation,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type Turn = {
  id?: string;
  question: string;
  response?: ChatResponse | AssistantRunResponse;
  error?: string;
  // Streaming state (live token output before the final response arrives).
  streaming?: boolean;
  streamingText?: string;
  streamSources?: Citation[];
  runId?: string;
  mode?: string;
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

// ─── Thinking / Status Indicator ──────────────────────────────────────────────

const THINKING_PHASES = [
  { label: "Routing your request",   duration: 1800 },
  { label: "Searching knowledge",    duration: 2200 },
  { label: "Reasoning through it",   duration: 2000 },
  { label: "Composing answer",       duration: 99999 },
];

function ThinkingIndicator({ mode = "thinking" }: { mode?: "thinking" | "executing" }) {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    setPhaseIndex(0);
    setVisible(true);
  }, [mode]);

  useEffect(() => {
    const phase = THINKING_PHASES[phaseIndex];
    if (!phase || phase.duration === 99999) return;

    const t = setTimeout(() => {
      setVisible(false);
      setTimeout(() => {
        setPhaseIndex((p) => Math.min(p + 1, THINKING_PHASES.length - 1));
        setVisible(true);
      }, 200);
    }, phase.duration);

    return () => clearTimeout(t);
  }, [phaseIndex]);

  const label = mode === "executing"
    ? "Executing workflow"
    : THINKING_PHASES[phaseIndex]?.label ?? "Thinking";

  return (
    <div className="aira-thinking-pill fade-up">
      {/* Animated sparkles logo */}
      <span className="aira-thinking-icon">
        <Sparkles className="h-3.5 w-3.5" />
      </span>

      {/* Animated dots */}
      <span className="aira-thinking-dots" aria-hidden>
        <span /><span /><span />
      </span>

      {/* Phase label */}
      <span
        className={cn(
          "aira-thinking-label",
          visible ? "aira-thinking-label--in" : "aira-thinking-label--out"
        )}
      >
        {label}
      </span>
    </div>
  );
}

// ─── Animated AIRA-X Logo ────────────────────────────────────────────────────

function AiraLogo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizeMap = {
    sm: "h-7 w-7",
    md: "h-10 w-10",
    lg: "h-14 w-14",
  };
  const iconMap = {
    sm: "h-3.5 w-3.5",
    md: "h-5 w-5",
    lg: "h-7 w-7",
  };

  return (
    <span className={cn("aira-logo", sizeMap[size])}>
      <span className="aira-logo-ring aira-logo-ring--outer" />
      <span className="aira-logo-ring aira-logo-ring--inner" />
      <Sparkles className={cn("aira-logo-icon", iconMap[size])} />
    </span>
  );
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function getWorkflowStatusClass(status?: string) {
  if (status === "completed" || status === "success") return "status-success";
  if (status === "failed" || status === "rejected" || status === "blocked") return "status-danger";
  if (status === "requires_approval" || status === "retrying" || status === "pending" || status === "running") return "status-warning";
  return "status-info";
}

function getAssistantResponse(response?: ChatResponse | AssistantRunResponse): AssistantRunResponse | null {
  if (response && "response_type" in response) return response;
  return null;
}

// ─── Primitive Components ─────────────────────────────────────────────────────

function InfoTile({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="aira-info-tile">
      <p className="aira-info-tile__label">{label}</p>
      <p className={cn("aira-info-tile__value", mono && "font-mono text-xs")}>{value}</p>
    </div>
  );
}

function CodeBlock({ value, fallback = "No data available." }: { value?: string; fallback?: string }) {
  return (
    <pre className="aira-code-block">{value?.trim() || fallback}</pre>
  );
}

function RunBadge({ children, className }: { children: ReactNode; className: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wide uppercase", className)}>
      {children}
    </span>
  );
}

function PanelHeader({ icon, title, description }: { icon: ReactNode; title: string; description?: string }) {
  return (
    <div className="mb-5 flex items-start gap-3">
      <div className="aira-panel-icon">
        {icon}
      </div>
      <div>
        <h2 className="text-sm font-bold text-[var(--text-strong)] leading-5">{title}</h2>
        {description && (
          <p className="mt-0.5 text-xs leading-5 text-[var(--text-muted)]">{description}</p>
        )}
      </div>
    </div>
  );
}

// ─── Git Preflight Panels ─────────────────────────────────────────────────────

function GitWritePreflight({ context }: { context: ApprovalContext }) {
  return (
    <div className="mt-4 aira-preflight aira-preflight--warning">
      <PanelHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Git Preflight Summary"
        description="Review repository changes before approving this Git write action."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <InfoTile label="Current Branch" value={context.branch || "Unknown"} />
        <InfoTile label="Git Action" value={context.pending_action || "Unknown action"} />
      </div>
      {context.commit_message && (
        <div className="mt-3"><InfoTile label="Commit Message" value={context.commit_message} /></div>
      )}
      <div className="mt-3">
        <p className="mb-2 text-xs font-bold uppercase tracking-widest text-[var(--text-subtle)]">Changed Files</p>
        <CodeBlock value={context.changed_files} fallback="No changed files detected." />
      </div>
      <div className="mt-3">
        <p className="mb-2 text-xs font-bold uppercase tracking-widest text-[var(--text-subtle)]">Diff Summary</p>
        <CodeBlock value={context.diff_summary} fallback="No diff summary available." />
      </div>
    </div>
  );
}

function GitPushPreflight({ context }: { context: ApprovalContext }) {
  return (
    <div className="mt-4 aira-preflight aira-preflight--danger">
      <PanelHeader
        icon={<UploadCloud className="h-4 w-4" />}
        title="Git Push Preflight Summary"
        description="Review remote target, tracking status, and recent commits before approving."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <InfoTile label="Target Remote" value={context.target_remote || "origin"} />
        <InfoTile label="Target Branch" value={context.target_branch || context.branch || "Unknown branch"} />
        <InfoTile label="Current Branch" value={context.branch || "Unknown"} />
        <InfoTile label="Git Action" value={context.pending_action || "Unknown action"} />
      </div>
      {[
        { label: "Branch Tracking Status", value: context.status_branch, fallback: "No branch tracking status available." },
        { label: "Remote Info", value: context.remote_info, fallback: "No remote info available." },
        { label: "Latest Local Commit", value: context.last_commit, fallback: "No latest commit available." },
        { label: "Recent Local Commits", value: context.recent_commits, fallback: "No recent commits available." },
      ].map(({ label, value, fallback }) => (
        <div className="mt-3" key={label}>
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-[var(--text-subtle)]">{label}</p>
          <CodeBlock value={value} fallback={fallback} />
        </div>
      ))}
    </div>
  );
}

function ApprovalContextPanel({ context }: { context?: ApprovalContext | null }) {
  if (!context) return null;
  if (context.type === "git_write_preflight") return <GitWritePreflight context={context} />;
  if (context.type === "git_push_preflight") return <GitPushPreflight context={context} />;
  return null;
}

// ─── Cleanup Actions ──────────────────────────────────────────────────────────

function CleanupActions({ memory }: { memory: any }) {
  const cleanupActions = memory?.cleanup_actions || [];
  if (!Array.isArray(cleanupActions) || cleanupActions.length === 0) return null;

  return (
    <TechnicalDetailsPanel summary="Cleanup trace">
      <div className="space-y-2.5">
        {cleanupActions.map((cleanup: any, index: number) => (
          <div key={`${cleanup.tool_action}-${index}`} className="aira-info-tile text-xs">
            <p><strong className="text-[var(--text-strong)]">Reason:</strong> {cleanup.reason}</p>
            <p className="mt-1"><strong className="text-[var(--text-strong)]">Status:</strong> {cleanup.result?.success ? "successful" : "failed"}</p>
            <p className="mt-1"><strong className="text-[var(--text-strong)]">Tool:</strong> {cleanup.tool_name}:{cleanup.tool_action}</p>
            {cleanup.result?.command && (
              <p className="mt-1"><strong className="text-[var(--text-strong)]">Command:</strong> {cleanup.result.command}</p>
            )}
          </div>
        ))}
      </div>
    </TechnicalDetailsPanel>
  );
}

// ─── Technical Detail Panels ──────────────────────────────────────────────────

function AssistantTurnTechnicalDetails({ response }: { response: AssistantRunResponse }) {
  const workflow = response.workflow;
  const rows: Array<{ label: string; value: string; mono?: boolean }> = [];

  if (response.run_id) rows.push({ label: "Run ID", value: response.run_id, mono: true });
  if (workflow?.decision) rows.push({ label: "Decision", value: String(workflow.decision) });
  if (response.metadata?.tool_name) rows.push({ label: "Tool", value: `${response.metadata.tool_name}:${response.metadata.tool_action || "action"}`, mono: true });
  if (Array.isArray(response.metadata?.response_types)) rows.push({ label: "Task routes", value: response.metadata.response_types.join(", ") });
  if (rows.length === 0) return null;

  return (
    <TechnicalDetailsPanel className="mt-4">
      <TechnicalDetailsGrid>
        {rows.map((row) => <TechnicalDetailRow key={row.label} label={row.label} value={row.value} mono={row.mono} />)}
      </TechnicalDetailsGrid>
    </TechnicalDetailsPanel>
  );
}

function collectWorkflowTechnicalRows(response: AiraXResponse) {
  const rows: Array<{ label: string; value: string; mono?: boolean }> = [
    { label: "Status", value: response.status || "unknown" },
    { label: "Decision", value: response.decision || "unknown" },
  ];
  if (response.run_id) rows.push({ label: "Run ID", value: response.run_id, mono: true });

  const agents = [...new Set((response.plan || []).map((s) => s.assigned_agent).filter(Boolean))];
  if (agents.length > 0) rows.push({ label: "Agents", value: agents.join(", ") });

  const toolActions = [...new Set((response.plan || []).filter((s) => s.tool_name && s.tool_action).map((s) => `${s.tool_name}:${s.tool_action}`))];
  if (toolActions.length > 0) rows.push({ label: "Tool actions", value: toolActions.join(" · "), mono: true });

  return rows;
}

// ─── Turn Card ────────────────────────────────────────────────────────────────

function ResearchTurnCard({ turn }: { turn: Turn }) {
  const assistantResponse = getAssistantResponse(turn.response);
  const multiTask = assistantResponse && isMultiTaskResponse(assistantResponse) ? assistantResponse : null;
  const taskCount = multiTask?.metadata?.task_count ?? 0;
  const failedTasks = multiTask?.metadata?.failed_tasks ?? [];
  const completedTasks = taskCount > 0 ? Math.max(taskCount - failedTasks.length, 0) : 0;

  return (
    <div className="fade-up space-y-3">
      {/* User bubble */}
      <div className="flex justify-end">
        <div className="aira-user-bubble">
          {turn.question}
        </div>
      </div>

      {/* Error state */}
      {turn.error && (
        <div className="aira-card aira-card--danger p-4 text-sm">
          <div className="flex items-center gap-2 font-semibold text-[var(--danger)]">
            <XCircle className="h-4 w-4 shrink-0" />
            {turn.error}
          </div>
        </div>
      )}

      {/* Live streaming card (tokens arriving before the final response) */}
      {turn.streaming && !turn.response && (
        <div className="aira-answer-card">
          <div className="flex items-center gap-2.5 mb-4">
            <AiraLogo size="sm" />
            <p className="text-sm font-bold text-[var(--text-strong)] leading-4">
              AIRA-X{turn.mode ? ` · ${turn.mode.replace(/_/g, " ")}` : ""}
            </p>
          </div>
          <div className="aira-answer-body">
            {turn.streamingText ? (
              <AssistantAnswerContent answer={turn.streamingText} />
            ) : (
              <span className="text-sm text-[var(--text-muted)]">Thinking…</span>
            )}
            <span className="ml-0.5 inline-block animate-pulse text-[var(--accent)]">▌</span>
          </div>
          {turn.streamSources && turn.streamSources.length > 0 && (
            <div className="mt-4 aira-citations-block">
              <p className="mb-2.5 text-xs font-bold uppercase tracking-widest text-[var(--text-subtle)]">Sources</p>
              <CitationList citations={turn.streamSources} />
            </div>
          )}
        </div>
      )}

      {/* Answer card */}
      {turn.response && (
        <div className="aira-answer-card">
          {/* Header row */}
          <div className="flex items-center gap-2.5 mb-4">
            <AiraLogo size="sm" />
            <div>
              <p className="text-sm font-bold text-[var(--text-strong)] leading-4">
                {multiTask ? "Multi-task results" : "AIRA-X"}
              </p>
              {multiTask && taskCount > 0 && (
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                  {failedTasks.length > 0
                    ? `${completedTasks} completed · ${failedTasks.length} failed`
                    : `${taskCount} tasks completed`}
                </p>
              )}
            </div>
          </div>

          {/* Answer body */}
          <div className="aira-answer-body">
            <AssistantAnswerContent answer={turn.response.answer} />
          </div>

          {/* Citations */}
          {turn.response.citations.length > 0 && (
            <div className="mt-4 aira-citations-block">
              <p className="mb-2.5 text-xs font-bold uppercase tracking-widest text-[var(--text-subtle)]">Sources</p>
              <CitationList citations={turn.response.citations} />
            </div>
          )}

          {/* Technical details */}
          {assistantResponse && (
            assistantResponse.run_id ||
            assistantResponse.workflow?.decision ||
            assistantResponse.metadata?.tool_name ||
            Array.isArray(assistantResponse.metadata?.response_types)
          ) && (
            <AssistantTurnTechnicalDetails response={assistantResponse} />
          )}

          {/* Streamed-turn meta: route + run id */}
          {(turn.runId || turn.mode) && (
            <p className="mt-3 text-[11px] text-[var(--text-subtle)]">
              {turn.mode ? turn.mode.replace(/_/g, " ") : "answer"}
              {turn.runId ? ` · run ${turn.runId.slice(0, 8)}` : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Workspace Shortcut Links ─────────────────────────────────────────────────

function AssistantWorkspaceLinks({ onUploadClick }: { onUploadClick: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-2 mt-8">
      {[
        { href: "/documents", icon: <Library className="h-3.5 w-3.5" />, label: "Knowledge" },
        { href: "/workflows", icon: <Workflow className="h-3.5 w-3.5" />, label: "Workflows" },
        { href: "/approvals", icon: <ShieldCheck className="h-3.5 w-3.5" />, label: "Approvals" },
        { href: "/history", icon: <Database className="h-3.5 w-3.5" />, label: "History" },
      ].map(({ href, icon, label }) => (
        <Link key={href} href={href} className="aira-shortcut-pill">
          {icon}{label}
        </Link>
      ))}
      <button type="button" onClick={onUploadClick} className="aira-shortcut-pill">
        <FileUp className="h-3.5 w-3.5" />
        Upload docs
      </button>
    </div>
  );
}

// ─── Suggestion Chips ─────────────────────────────────────────────────────────

function SuggestionChip({ label, prompt, onSelect }: { label: string; prompt: string; onSelect: (v: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(prompt)}
      className="aira-suggestion-chip"
    >
      <Sparkles className="h-3 w-3 text-[var(--accent)] shrink-0" />
      {label}
    </button>
  );
}

// ─── Home Stage ───────────────────────────────────────────────────────────────

function AiraHomeStage({
  question, setQuestion, busy, loading, onSubmit, onComposerFocus,
}: {
  question: string;
  setQuestion: (v: string) => void;
  busy: boolean;
  loading: boolean;
  onSubmit: (e: FormEvent) => Promise<void>;
  onComposerFocus: () => void;
}) {
  return (
    <section className="assistant-empty-shell w-full">
      <div className="w-full max-w-2xl text-center">
        {/* Animated logo */}
        <div className="flex justify-center mb-5">
          <AiraLogo size="lg" />
        </div>

        <p className="aira-kicker mb-3">AIRA-X Assistant</p>

        <h2 className="text-3xl font-black tracking-tight text-[var(--text-strong)] md:text-[2.6rem] md:leading-[1.1]">
          How can I help<br />
          <span className="aira-gradient-text">you today?</span>
        </h2>

        <p className="mx-auto mt-3 max-w-lg text-sm leading-7 text-[var(--text-muted)]">
          Ask anything, analyze documents, plan projects, or run a workflow.
          Routing is handled automatically.
        </p>

        {/* Composer */}
        <form onSubmit={onSubmit} className="aira-home-composer mt-8 text-left">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onFocus={onComposerFocus}
            placeholder="Message AIRA-X..."
            className="aira-home-textarea"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!busy && question.trim()) onSubmit(e as any);
              }
            }}
          />
          <div className="flex items-center justify-between px-1 pt-3 pb-1 border-t border-[var(--border)]">
            <p className="text-xs text-[var(--text-subtle)]">
              <kbd className="aira-kbd">↵</kbd> to send · <kbd className="aira-kbd">⇧↵</kbd> new line
            </p>
            <button
              disabled={busy || !question.trim()}
              className="aira-send-btn"
            >
              {loading
                ? <span className="aira-send-spinner" />
                : <Send className="h-3.5 w-3.5" />
              }
              {loading ? "Working…" : "Send"}
            </button>
          </div>
        </form>

        {/* Chips */}
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <SuggestionChip label="Explain a topic"   prompt="Explain "                           onSelect={setQuestion} />
          <SuggestionChip label="Summarize text"    prompt="Summarize the following text: "     onSelect={setQuestion} />
          <SuggestionChip label="Plan a project"    prompt="Create a detailed project plan for: " onSelect={setQuestion} />
        </div>
      </div>
    </section>
  );
}

// ─── Workflow Result Card ─────────────────────────────────────────────────────

function WorkflowResultCard({ response, approvalLoading, rejectionLoading, onApprove, onReject }: {
  response: AiraXResponse;
  approvalLoading: boolean;
  rejectionLoading: boolean;
  onApprove: () => Promise<void>;
  onReject: () => Promise<void>;
}) {
  const isCompleted = response.status === "completed";
  const isFailed = ["failed", "rejected", "blocked"].includes(response.status);
  const finalAnswer = response.final_answer || "No final answer yet.";

  return (
    <div className="aira-card aira-card--workflow">
      {/* Status header */}
      <div className="flex items-start gap-3 mb-5">
        <div className={cn(
          "aira-status-icon",
          isCompleted ? "aira-status-icon--success" : isFailed ? "aira-status-icon--danger" : "aira-status-icon--warning"
        )}>
          {isCompleted ? <CheckCircle2 className="h-4 w-4" /> : isFailed ? <XCircle className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
        </div>
        <div>
          <RunBadge className={cn("mb-1.5", getWorkflowStatusClass(response.status))}>
            {response.status || "unknown"}
          </RunBadge>
          <h2 className="text-lg font-black tracking-tight text-[var(--text-strong)]">
            {isCompleted ? "Execution complete" : isFailed ? "Execution stopped" : "Execution in progress"}
          </h2>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            AIRA-X completed the workflow and prepared the result below.
          </p>
        </div>
      </div>

      {/* Final answer */}
      <div className="aira-final-answer">
        <p className="aira-section-label mb-3">Final Answer</p>
        <AssistantAnswerContent answer={finalAnswer} />
      </div>

      {/* Approval gate */}
      {response.requires_approval && (
        <div className="mt-4 aira-approval-gate">
          <PanelHeader
            icon={<ShieldCheck className="h-4 w-4" />}
            title="Approval Required"
            description="This action can modify your environment and needs permission before continuing."
          />
          <div className="aira-info-tile text-sm mb-4">
            <strong>Pending action:</strong> {response.pending_action || "Unknown action"}
          </div>
          <ApprovalContextPanel context={response.approval_context} />
          <div className="mt-4 flex flex-wrap gap-2.5">
            <button
              type="button"
              onClick={onApprove}
              disabled={approvalLoading || rejectionLoading}
              className="aira-btn aira-btn--warning"
            >
              {approvalLoading ? "Approving…" : "Approve & Continue"}
            </button>
            <button
              type="button"
              onClick={onReject}
              disabled={approvalLoading || rejectionLoading}
              className="aira-btn aira-btn--ghost-danger"
            >
              <XCircle className="h-3.5 w-3.5" />
              {rejectionLoading ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </div>
      )}

      {/* Technical rows */}
      <TechnicalDetailsPanel className="mt-4">
        <TechnicalDetailsGrid>
          {collectWorkflowTechnicalRows(response).map((row) => (
            <TechnicalDetailRow key={row.label} label={row.label} value={row.value} mono={row.mono} />
          ))}
        </TechnicalDetailsGrid>
      </TechnicalDetailsPanel>

      <CleanupActions memory={response.memory} />
    </div>
  );
}

// ─── Execution Plan Card ──────────────────────────────────────────────────────

function ExecutionPlanCard({ steps }: { steps: AiraXStep[] }) {
  return (
    <TechnicalDetailsPanel
      className="aira-card mt-2 p-5"
      summary={`Execution plan · ${steps.length} step${steps.length === 1 ? "" : "s"}`}
    >
      <PanelHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Execution Plan"
        description="Step-by-step trace for this workflow run."
      />
      <div className="space-y-2.5">
        {steps.map((step) => (
          <div
            key={step.id}
            className={cn(
              "aira-step-card",
              (step.status === "failed" || step.status === "blocked" || step.status === "rejected")
                ? "aira-step-card--failed"
                : ""
            )}
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <p className="text-sm font-semibold text-[var(--text-strong)]">
                <span className="text-[var(--accent)] mr-1.5">{step.id}.</span>{step.title}
              </p>
              <RunBadge className={getWorkflowStatusClass(step.status)}>{step.status}</RunBadge>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-3">{step.description}</p>

            {step.result ? (
              <div className="aira-step-result">
                <AssistantAnswerContent answer={step.result} />
              </div>
            ) : (
              <p className="text-xs text-[var(--text-subtle)]">No result yet</p>
            )}

            {(step.assigned_agent || step.tool_name || step.tool_action) && (
              <TechnicalDetailsPanel className="mt-3" summary="Step details">
                <TechnicalDetailsGrid>
                  {step.assigned_agent && <TechnicalDetailRow label="Agent" value={step.assigned_agent} />}
                  {step.tool_name && <TechnicalDetailRow label="Tool" value={step.tool_name} />}
                  {step.tool_action && <TechnicalDetailRow label="Action" value={step.tool_action} mono />}
                </TechnicalDetailsGrid>
              </TechnicalDetailsPanel>
            )}

            {step.error && (
              <div className="mt-2.5 rounded-lg border border-[color-mix(in_srgb,var(--danger)_28%,transparent)] bg-[var(--danger-soft)] px-3 py-2 text-xs text-[var(--danger)]">
                <strong>Error:</strong> {step.error}
              </div>
            )}
          </div>
        ))}
      </div>
    </TechnicalDetailsPanel>
  );
}

// ─── Focus Composer Overlay ───────────────────────────────────────────────────

function FocusComposerOverlay({ question, setQuestion, busy, loading, airaXLoading, onSubmit, onClose }: {
  question: string;
  setQuestion: (v: string) => void;
  busy: boolean;
  loading: boolean;
  airaXLoading: boolean;
  onSubmit: (e: FormEvent) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <>
      <button type="button" aria-label="Close focus composer" onClick={onClose}
        className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm" />

      <form onSubmit={onSubmit}
        className="fixed left-1/2 top-1/2 z-50 w-[min(780px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 aira-focus-form research-composer chatgpt-composer">
        <div className="mb-3 flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <AiraLogo size="sm" />
            <span className="text-xs font-bold text-[var(--text-muted)]">Focused prompt</span>
          </div>
          <button type="button" onClick={onClose}
            className="aira-icon-btn" aria-label="Close">
            <XCircle className="h-4 w-4" />
          </button>
        </div>

        <textarea
          autoFocus
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Message AIRA-X…"
          className="aira-focus-textarea"
        />

        <div className="mt-3 flex items-center justify-between">
          <p className="text-xs text-[var(--text-subtle)]">
            <kbd className="aira-kbd">Esc</kbd> to exit focus mode
          </p>
          <button disabled={busy || !question.trim()} className="aira-send-btn">
            {loading || airaXLoading
              ? <span className="aira-send-spinner" />
              : <Send className="h-3.5 w-3.5" />
            }
            {loading || airaXLoading ? "Working…" : "Send"}
          </button>
        </div>
      </form>
    </>
  );
}

// ─── Inline Styles ────────────────────────────────────────────────────────────
// All new component CSS lives here as a single <style> injection so it works
// alongside your globals.css and Tailwind without extra config.

const AIRA_STYLES = `
/* ── Animated Logo ── */
.aira-logo {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.aira-logo-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid color-mix(in srgb, var(--accent) 46%, transparent);
  animation: airaRingPulse 2.8s ease-in-out infinite;
}
.aira-logo-ring--inner {
  inset: 3px;
  border-color: color-mix(in srgb, var(--secondary) 38%, transparent);
  animation-delay: 0.7s;
  animation-duration: 2.4s;
}
.aira-logo-icon {
  position: relative;
  z-index: 1;
  color: var(--accent);
  filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 60%, transparent));
  animation: airaIconShimmer 3s ease-in-out infinite;
}
@keyframes airaRingPulse {
  0%, 100% { opacity: 0.5; transform: scale(1); }
  50%       { opacity: 1;   transform: scale(1.12); }
}
@keyframes airaIconShimmer {
  0%, 100% { filter: drop-shadow(0 0 4px color-mix(in srgb, var(--accent) 50%, transparent)); }
  40%       { filter: drop-shadow(0 0 12px color-mix(in srgb, var(--accent) 90%, transparent)) drop-shadow(0 0 24px color-mix(in srgb, var(--secondary) 40%, transparent)); }
  70%       { filter: drop-shadow(0 0 8px color-mix(in srgb, var(--accent) 70%, transparent)); }
}

/* ── Thinking Pill ── */
.aira-thinking-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 0.5rem 1rem 0.5rem 0.75rem;
  backdrop-filter: blur(12px);
  box-shadow: var(--shadow-soft);
  max-width: fit-content;
}
.aira-thinking-icon {
  display: flex;
  align-items: center;
  color: var(--accent);
  animation: airaIconShimmer 2s ease-in-out infinite;
}
.aira-thinking-dots {
  display: flex;
  align-items: center;
  gap: 3px;
}
.aira-thinking-dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--accent);
  animation: airaThinkDot 1.4s ease-in-out infinite;
}
.aira-thinking-dots span:nth-child(2) { animation-delay: 0.18s; }
.aira-thinking-dots span:nth-child(3) { animation-delay: 0.36s; }
@keyframes airaThinkDot {
  0%, 80%, 100% { transform: scale(0.7); opacity: 0.4; }
  40%           { transform: scale(1.2); opacity: 1; }
}
.aira-thinking-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted);
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.aira-thinking-label--in  { opacity: 1; transform: translateY(0); }
.aira-thinking-label--out { opacity: 0; transform: translateY(4px); }

/* ── Cards ── */
.aira-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 1.25rem;
  background: var(--surface);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-card);
  transition: border-color 0.22s ease, box-shadow 0.22s ease;
}
.aira-card--workflow {
  padding: 1.4rem;
}
.aira-card--danger {
  border-color: color-mix(in srgb, var(--danger) 30%, transparent);
  background: var(--danger-soft);
}
html[data-theme="dark"] .aira-card::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(135deg,
    color-mix(in srgb, var(--accent) 10%, transparent),
    transparent 22%,
    transparent 72%,
    color-mix(in srgb, var(--secondary) 8%, transparent));
  border-radius: inherit;
}

/* ── Answer Card ── */
.aira-answer-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 1.25rem;
  background: var(--surface);
  backdrop-filter: blur(18px);
  box-shadow: var(--shadow-card);
  padding: 1.25rem;
}
html[data-theme="dark"] .aira-answer-card {
  background: linear-gradient(180deg,
    color-mix(in srgb, var(--surface) 90%, white 5%),
    var(--surface));
}

/* ── Answer Body ── */
.aira-answer-body {
  border: 1px solid var(--border);
  border-radius: 0.875rem;
  background: var(--surface-soft);
  padding: 1.1rem 1.25rem;
}

/* ── Citations Block ── */
.aira-citations-block {
  border: 1px solid var(--border);
  border-radius: 0.875rem;
  background: var(--surface-muted);
  padding: 0.875rem 1rem;
}

/* ── User Bubble ── */
.aira-user-bubble {
  max-width: min(36rem, 86%);
  border-radius: 1.1rem;
  border-bottom-right-radius: 0.25rem;
  background: var(--accent);
  color: var(--accent-foreground);
  padding: 0.7rem 1.1rem;
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.6;
  box-shadow: var(--shadow-soft);
}

/* ── Info Tile ── */
.aira-info-tile {
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  background: var(--surface-muted);
  padding: 0.7rem 0.875rem;
}
.aira-info-tile__label {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-subtle);
}
.aira-info-tile__value {
  margin-top: 0.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-strong);
  white-space: pre-wrap;
  word-break: break-words;
}

/* ── Code Block ── */
.aira-code-block {
  max-height: 13rem;
  overflow: auto;
  white-space: pre-wrap;
  border-radius: 0.75rem;
  padding: 0.75rem;
  font-size: 0.72rem;
  line-height: 1.6;
  border: 1px solid color-mix(in srgb, var(--accent) 14%, transparent);
  background: var(--pre-bg);
  color: #c8f7dc;
}

/* ── Panel Icon ── */
.aira-panel-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.875rem;
  border: 1px solid var(--border);
  background: var(--accent-soft);
  color: var(--accent);
}

/* ── Status Icon ── */
.aira-status-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.875rem;
  border: 1px solid;
}
.aira-status-icon--success {
  border-color: color-mix(in srgb, var(--success) 34%, transparent);
  background: var(--success-soft);
  color: var(--success);
}
.aira-status-icon--danger {
  border-color: color-mix(in srgb, var(--danger) 34%, transparent);
  background: var(--danger-soft);
  color: var(--danger);
}
.aira-status-icon--warning {
  border-color: color-mix(in srgb, var(--warning) 34%, transparent);
  background: var(--warning-soft);
  color: var(--warning);
}

/* ── Final Answer Block ── */
.aira-final-answer {
  border: 1px solid var(--border-strong);
  border-radius: 1rem;
  background: var(--surface-soft);
  padding: 1.1rem 1.25rem;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 8%, transparent);
}

/* ── Section Label ── */
.aira-section-label {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--text-subtle);
}

/* ── Approval Gate ── */
.aira-approval-gate {
  border-radius: 1rem;
  border: 1px solid color-mix(in srgb, var(--warning) 32%, transparent);
  background: var(--warning-soft);
  padding: 1.1rem;
}

/* ── Preflight Panels ── */
.aira-preflight {
  border-radius: 1rem;
  padding: 1rem;
}
.aira-preflight--warning {
  border: 1px solid color-mix(in srgb, var(--warning) 32%, transparent);
  background: var(--warning-soft);
}
.aira-preflight--danger {
  border: 1px solid color-mix(in srgb, var(--danger) 32%, transparent);
  background: var(--danger-soft);
}

/* ── Step Card ── */
.aira-step-card {
  border-radius: 1rem;
  border: 1px solid var(--border);
  background: var(--surface-soft);
  padding: 0.875rem 1rem;
}
.aira-step-card--failed {
  border-color: color-mix(in srgb, var(--danger) 30%, transparent);
  background: var(--danger-soft);
}
.aira-step-result {
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  background: var(--surface-muted);
  padding: 0.75rem;
  font-size: 0.85rem;
}

/* ── Buttons ── */
.aira-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border-radius: 0.75rem;
  padding: 0.6rem 1.1rem;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
  border: 1px solid transparent;
}
.aira-btn:hover:not(:disabled) { opacity: 0.92; transform: translateY(-1px); }
.aira-btn:active:not(:disabled) { transform: scale(0.98); }
.aira-btn:disabled { cursor: not-allowed; opacity: 0.5; }
.aira-btn--warning {
  background: var(--warning);
  color: #fff;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--warning) 28%, transparent);
}
.aira-btn--ghost-danger {
  background: var(--surface-soft);
  border-color: color-mix(in srgb, var(--danger) 32%, transparent);
  color: var(--danger);
}
.aira-btn--ghost-danger:hover:not(:disabled) { background: var(--danger-soft); }

/* ── Icon Button ── */
.aira-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.625rem;
  border: 1px solid var(--border);
  background: var(--surface-soft);
  color: var(--text-muted);
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.aira-icon-btn:hover { border-color: var(--border-strong); color: var(--text-strong); background: var(--surface-hover); }

/* ── Send Button ── */
.aira-send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border-radius: 999px;
  border: none;
  background: var(--accent);
  color: var(--accent-foreground);
  padding: 0.55rem 1.1rem;
  font-size: 0.82rem;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 16px color-mix(in srgb, var(--accent) 32%, transparent);
  transition: opacity 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.aira-send-btn:hover:not(:disabled) {
  opacity: 0.92;
  box-shadow: 0 6px 22px color-mix(in srgb, var(--accent) 44%, transparent);
}
.aira-send-btn:disabled { cursor: not-allowed; opacity: 0.5; box-shadow: none; }
.aira-send-spinner {
  display: block;
  width: 0.875rem;
  height: 0.875rem;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--accent-foreground) 32%, transparent);
  border-top-color: var(--accent-foreground);
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Kicker ── */
.aira-kicker {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-muted);
  padding: 0.28rem 0.85rem;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
}

/* ── Home Composer ── */
.aira-home-composer {
  border: 1px solid var(--border);
  border-radius: 1.35rem;
  background: var(--surface);
  backdrop-filter: blur(20px);
  padding: 0.75rem;
  box-shadow: var(--shadow-card);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.aira-home-composer:focus-within {
  border-color: var(--border-strong);
  box-shadow:
    var(--shadow-card),
    0 0 0 4px color-mix(in srgb, var(--accent) 10%, transparent);
}
.aira-home-textarea {
  width: 100%;
  min-height: 5.5rem;
  resize: none;
  border: none;
  border-radius: 0.875rem;
  background: transparent;
  padding: 0.875rem 1rem;
  font-size: 0.875rem;
  color: var(--text-strong);
  caret-color: var(--accent);
  outline: none;
  line-height: 1.65;
}
.aira-home-textarea::placeholder { color: var(--text-subtle); }

/* ── Focus Form ── */
.aira-focus-form {
  border: 1px solid var(--border-strong);
  border-radius: 1.5rem;
  background: var(--surface);
  backdrop-filter: blur(24px);
  padding: 1rem;
  box-shadow:
    0 32px 100px rgba(0,0,0,0.5),
    0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent),
    0 0 48px color-mix(in srgb, var(--accent) 12%, transparent);
}
.aira-focus-textarea {
  width: 100%;
  min-height: 9rem;
  resize: none;
  border-radius: 0.875rem;
  border: 1px solid var(--border);
  background: var(--surface-strong);
  padding: 1rem 1.1rem;
  font-size: 0.9375rem;
  line-height: 1.7;
  color: var(--text-strong);
  caret-color: var(--accent);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.aira-focus-textarea:focus {
  border-color: var(--border-strong);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 10%, transparent);
}

/* ── Shortcut Pill ── */
.aira-shortcut-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 0.42rem 0.875rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-muted);
  text-decoration: none;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.aira-shortcut-pill:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text-strong);
  opacity: 1;
}

/* ── Suggestion Chip ── */
.aira-suggestion-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 0.48rem 0.9rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.aira-suggestion-chip:hover {
  border-color: color-mix(in srgb, var(--accent) 38%, transparent);
  background: var(--accent-soft);
  color: var(--text-strong);
  opacity: 1;
}

/* ── KBD ── */
.aira-kbd {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 0.3rem;
  background: var(--surface-muted);
  padding: 0.05rem 0.35rem;
  font-size: 0.68rem;
  font-family: inherit;
  color: var(--text-muted);
}
`;

function AiraStyles() {
  return <style dangerouslySetInnerHTML={{ __html: AIRA_STYLES }} />;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [question, setQuestion]             = useState("");
  const [composerFocused, setComposerFocused] = useState(false);
  const [loading, setLoading]               = useState(false);
  const [airaXLoading, setAiraXLoading]     = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [rejectionLoading, setRejectionLoading] = useState(false);
  const [uploadLoading, setUploadLoading]   = useState(false);
  const [uploadMessage, setUploadMessage]   = useState("");
  const [uploadError, setUploadError]       = useState("");
  const [turns, setTurns]                   = useState<Turn[]>([]);
  const [airaXResponse, setAiraXResponse]   = useState<AiraXResponse | null>(null);
  const [sessionId] = useState(() =>
    typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now())
  );
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const threadBottomRef = useRef<HTMLDivElement>(null);

  const busy = loading || airaXLoading || approvalLoading || rejectionLoading || uploadLoading;
  const threadIsEmpty = useMemo(() => turns.length === 0 && !airaXResponse, [turns.length, airaXResponse]);

  // Escape to close focus overlay
  useEffect(() => {
    if (!composerFocused) return;
    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") setComposerFocused(false); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [composerFocused]);

  // Scroll to bottom after new turn
  useEffect(() => {
    threadBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, loading, airaXResponse]);

  function patchTurnById(id: string, patch: Partial<Turn>) {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }

  function removeTurnById(id: string) {
    setTurns((prev) => prev.filter((t) => t.id !== id));
  }

  function modeToResponseType(mode?: string): AssistantRunResponse["response_type"] {
    switch (mode) {
      case "web_research": return "web_research";
      case "execution":
      case "research_then_execution": return "execution_result";
      case "document_qa": return "document_research";
      case "general_chat":
      case "self_memory": return "casual_chat";
      default: return "general_answer";
    }
  }

  function applyNonStreamingResponse(turnId: string, trimmed: string, response: AssistantRunResponse) {
    const shouldRenderAsWorkflow =
      !isMultiTaskResponse(response) &&
      (response.response_type === "execution_result" || response.response_type === "approval_required");

    if (shouldRenderAsWorkflow) {
      const workflowRun = assistantWorkflowToAiraXRun(response.workflow);
      if (workflowRun) {
        setAiraXResponse(workflowRun);
        setTurns([]);
        return;
      }
    }
    setAiraXResponse(null);
    patchTurnById(turnId, { streaming: false, streamingText: undefined, response });
  }

  async function handleUnifiedAssistant(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;

    setComposerFocused(false);
    setQuestion("");
    setLoading(true);
    setAiraXLoading(false);

    const turnId =
      typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    setTurns((prev) => [...prev, { id: turnId, question: trimmed, streaming: true, streamingText: "" }]);

    let finalData: Record<string, unknown> | null = null;

    try {
      await streamAiraX(
        trimmed,
        {
          onToken: (text) =>
            setTurns((prev) =>
              prev.map((t) =>
                t.id === turnId ? { ...t, streamingText: (t.streamingText || "") + text } : t
              )
            ),
          onSource: (source) =>
            setTurns((prev) =>
              prev.map((t) =>
                t.id === turnId
                  ? { ...t, streamSources: [...(t.streamSources || []), source as unknown as Citation] }
                  : t
              )
            ),
          onTrace: (data) => {
            if (typeof data?.mode === "string") patchTurnById(turnId, { mode: data.mode });
          },
          onFinal: (data) => {
            finalData = data;
          },
          onError: (message) => {
            throw new Error(message);
          },
        },
        { sessionId }
      );

      if (!finalData) {
        throw new Error("Stream ended without a final response.");
      }

      const final = finalData as AssistantRunResponse & Record<string, unknown>;
      const mode = String((final as Record<string, unknown>).mode ?? "");

      // Document Q&A still flows through the legacy route (unchanged for now):
      // the supervisor only returns a placeholder, so fetch the real answer.
      if (mode === "document_qa") {
        const real = await runAssistant(trimmed, true);
        applyNonStreamingResponse(turnId, trimmed, real);
        return;
      }

      // Execution / approval turns render as a workflow card.
      const isWorkflow =
        mode === "execution" ||
        mode === "research_then_execution" ||
        (final as Record<string, unknown>).requires_approval === true ||
        (final as Record<string, unknown>).status === "requires_approval";

      if (isWorkflow) {
        const run = assistantWorkflowToAiraXRun(final as unknown as Parameters<typeof assistantWorkflowToAiraXRun>[0]);
        if (run) {
          setAiraXResponse(run);
          removeTurnById(turnId);
          return;
        }
      }

      // Chat / web research / self-memory: finalize the streamed bubble.
      const synthetic: AssistantRunResponse = {
        response_type: modeToResponseType(mode),
        answer: String(final.message ?? (final as Record<string, unknown>).final_answer ?? ""),
        citations: Array.isArray(final.sources) ? (final.sources as Citation[]) : [],
        workflow: null,
        run_id: typeof final.run_id === "string" ? final.run_id : null,
        metadata: ((final as Record<string, unknown>).meta as Record<string, unknown>) ?? {},
      };
      setAiraXResponse(null);
      patchTurnById(turnId, {
        streaming: false,
        response: synthetic,
        runId: synthetic.run_id ?? undefined,
        mode,
      });
    } catch (streamError) {
      // Graceful fallback to the non-streaming endpoint.
      try {
        const response = await runAssistant(trimmed, true);
        applyNonStreamingResponse(turnId, trimmed, response);
      } catch (fallbackError) {
        const message =
          fallbackError instanceof Error ? fallbackError.message : "AIRA-X assistant failed.";
        patchTurnById(turnId, { streaming: false, streamingText: undefined, error: message });
      }
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
    if (!files || files.length === 0) return;
    setUploadLoading(true);
    setUploadMessage("");
    setUploadError("");
    try {
      const result = await uploadDocuments(files);
      const count = result.documents?.length || files.length;
      setUploadMessage(`${count} document${count === 1 ? "" : "s"} uploaded and indexed.`);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Document upload failed.");
    } finally {
      setUploadLoading(false);
      event.target.value = "";
    }
  }

  async function handleSubmit(event: FormEvent) {
    await handleUnifiedAssistant(event);
  }

  return (
    <>
      <AiraStyles />

      <div className={cn(
        "mx-auto flex min-h-[calc(100vh-64px)] w-full flex-col gap-4 px-4 pb-6",
        threadIsEmpty ? "max-w-2xl" : "max-w-3xl",
        "aira-chat-page"
      )}>
        <input ref={uploadInputRef} type="file" multiple className="hidden" onChange={handleUploadDocuments} />

        {/* Upload feedback */}
        {(uploadMessage || uploadError) && (
          <div className={cn(
            "rounded-xl border px-4 py-2.5 text-sm font-semibold",
            uploadError
              ? "border-[color-mix(in_srgb,var(--danger)_30%,transparent)] bg-[var(--danger-soft)] text-[var(--danger)]"
              : "border-[color-mix(in_srgb,var(--success)_30%,transparent)] bg-[var(--success-soft)] text-[var(--success)]"
          )}>
            {uploadError || uploadMessage}
          </div>
        )}

        {/* Main content */}
        <div
          className="aira-focus-content flex flex-1 flex-col gap-4"
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
              <AssistantWorkspaceLinks onUploadClick={() => uploadInputRef.current?.click()} />
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-4 pt-2">
              {/* Thread */}
              {turns.map((turn, index) => (
                <ResearchTurnCard key={`${turn.question}-${index}`} turn={turn} />
              ))}

              {/* Thinking indicator */}
              {loading && <ThinkingIndicator mode="thinking" />}
              {airaXLoading && <ThinkingIndicator mode="executing" />}

              {/* Workflow result */}
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

              <div ref={threadBottomRef} />
            </div>
          )}

          {/* Sticky composer */}
          {!threadIsEmpty && (
            <form
              onSubmit={handleSubmit}
              className="aira-home-composer sticky bottom-4"
            >
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onFocus={() => setComposerFocused(true)}
                placeholder="Message AIRA-X…"
                className="aira-home-textarea"
                style={{ minHeight: "5rem" }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (!busy && question.trim()) handleSubmit(e as any);
                  }
                }}
              />
              <div className="flex items-center justify-between px-1 pt-3 pb-1 border-t border-[var(--border)]">
                <div className="inline-flex items-center gap-1.5 text-xs text-[var(--text-subtle)]">
                  <ShieldAlert className="h-3.5 w-3.5 text-[var(--warning)]" />
                  Approval-gated when needed
                </div>
                <button disabled={busy || !question.trim()} className="aira-send-btn">
                  {loading || airaXLoading
                    ? <span className="aira-send-spinner" />
                    : <Send className="h-3.5 w-3.5" />
                  }
                  {loading || airaXLoading ? "Working…" : "Send"}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Focus overlay */}
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
    </>
  );
}