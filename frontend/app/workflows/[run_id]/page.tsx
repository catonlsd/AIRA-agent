"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  GitBranch,
  History,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  UploadCloud,
  Workflow,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  approveAiraX,
  deleteAiraXRun,
  getAiraXRun,
  rejectAiraX,
} from "@/lib/api";
import { cn } from "@/lib/utils";

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

type ApprovalResolution = {
  status?: string;
  action?: string;
  requested_at?: string;
  completed_at?: string;
  final_status?: string;
  final_decision?: string;
  error?: string;
  previous_status?: string;
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
  user_goal: string;
  status: string;
  decision: string;
  final_answer: string | null;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  current_step?: number | null;
  retry_count?: number;
  plan: WorkflowStep[];
  execution_outputs: any[];
  memory: any;
  workflow_logs?: WorkflowLog[];
  workflow_summary?: any;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext | null;
  approval_context_type?: string;
  approval_in_progress?: boolean;
  approval_resolution?: ApprovalResolution;
  approval_resolution_status?: string;
  approval_resolution_action?: string;
  cleanup_count?: number;
  has_cleanup?: boolean;
};

type StatusTone = "success" | "danger" | "warning" | "info" | "neutral";

function formatDateTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function parseTimestamp(value?: string | null) {
  if (!value) {
    return null;
  }

  const timestamp = new Date(value).getTime();

  return Number.isNaN(timestamp) ? null : timestamp;
}

function formatDurationFromMilliseconds(durationMs: number) {
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    return "Not available";
  }

  const totalSeconds = Math.floor(durationMs / 1000);

  if (totalSeconds < 60) {
    return `${Math.max(totalSeconds, 1)} sec`;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;

  const parts = [];

  if (days > 0) {
    parts.push(`${days}d`);
  }

  if (hours > 0) {
    parts.push(`${hours}h`);
  }

  if (minutes > 0 || parts.length === 0) {
    parts.push(`${minutes}m`);
  }

  return parts.join(" ");
}

function getWorkflowDuration(run: WorkflowRun) {
  const createdAt = parseTimestamp(run.created_at);
  const completedAt = parseTimestamp(run.completed_at);

  if (!createdAt || !completedAt) {
    return "Not completed yet";
  }

  return formatDurationFromMilliseconds(completedAt - createdAt);
}

function isApprovalProcessing(run?: WorkflowRun | null) {
  return (
    run?.approval_in_progress === true ||
    run?.memory?.approval_in_progress === true
  );
}

function isWaitingForApproval(run?: WorkflowRun | null) {
  return Boolean(run?.requires_approval || run?.status === "requires_approval");
}

function getApprovalContext(run?: WorkflowRun | null): ApprovalContext | null {
  if (!run) {
    return null;
  }

  return run.approval_context || run.memory?.approval_context || null;
}

function getApprovalContextType(run?: WorkflowRun | null) {
  const context = getApprovalContext(run);

  return run?.approval_context_type || context?.type || "";
}

function isGitWritePreflight(run?: WorkflowRun | null) {
  return getApprovalContextType(run) === "git_write_preflight";
}

function isGitPushPreflight(run?: WorkflowRun | null) {
  return getApprovalContextType(run) === "git_push_preflight";
}

function getApprovalResolution(run: WorkflowRun): ApprovalResolution | null {
  const directResolution = run.approval_resolution;
  const memoryResolution = run.memory?.approval_resolution;

  if (
    directResolution &&
    typeof directResolution === "object" &&
    Object.keys(directResolution).length > 0
  ) {
    return directResolution;
  }

  if (
    memoryResolution &&
    typeof memoryResolution === "object" &&
    Object.keys(memoryResolution).length > 0
  ) {
    return memoryResolution;
  }

  if (isApprovalProcessing(run)) {
    return {
      status: "processing",
      action: run.pending_action || run.memory?.pending_action,
    };
  }

  return null;
}

function getCleanupActions(run: WorkflowRun) {
  const cleanupActions = run.memory?.cleanup_actions || [];

  return Array.isArray(cleanupActions) ? cleanupActions : [];
}

function getStatusTone(status?: string): StatusTone {
  if (status === "completed" || status === "approved") {
    return "success";
  }

  if (
    status === "failed" ||
    status === "rejected" ||
    status === "approved_but_resume_failed" ||
    status === "stale_processing_recovered"
  ) {
    return "danger";
  }

  if (
    status === "requires_approval" ||
    status === "retrying" ||
    status === "processing" ||
    status === "in_progress"
  ) {
    return "warning";
  }

  if (!status || status === "unknown" || status === "not_resolved") {
    return "neutral";
  }

  return "info";
}

function getToneClass(tone: StatusTone) {
  if (tone === "success") {
    return "status-success";
  }

  if (tone === "danger") {
    return "status-danger";
  }

  if (tone === "warning") {
    return "status-warning";
  }

  if (tone === "neutral") {
    return "border-[var(--border)] bg-[var(--surface-soft)] text-[var(--text-muted)]";
  }

  return "status-info";
}

function getStatusClass(status?: string) {
  return getToneClass(getStatusTone(status));
}

function getStatusIcon(status?: string) {
  if (status === "completed" || status === "approved") {
    return <CheckCircle2 className="h-3.5 w-3.5" />;
  }

  if (
    status === "failed" ||
    status === "rejected" ||
    status === "approved_but_resume_failed" ||
    status === "stale_processing_recovered"
  ) {
    return <XCircle className="h-3.5 w-3.5" />;
  }

  if (status === "requires_approval") {
    return <ShieldAlert className="h-3.5 w-3.5" />;
  }

  return <Clock className="h-3.5 w-3.5" />;
}

function getApprovalResolutionLabel(status?: string) {
  if (status === "approved") {
    return "Approved";
  }

  if (status === "rejected") {
    return "Rejected";
  }

  if (status === "approved_but_resume_failed") {
    return "Approved, resume failed";
  }

  if (status === "stale_processing_recovered") {
    return "Stale approval recovered";
  }

  if (status === "processing" || status === "in_progress") {
    return "Processing";
  }

  return "Not resolved";
}

function getActionLabel(status: string) {
  if (status === "rejected") {
    return "Rejected action";
  }

  if (status === "requires_approval") {
    return "Pending action";
  }

  return "Action";
}

function getStepStatusClass(status: string) {
  if (status === "completed" || status === "success") {
    return "status-success";
  }

  if (status === "failed" || status === "blocked" || status === "rejected") {
    return "status-danger";
  }

  if (status === "running" || status === "pending" || status === "retrying") {
    return "status-warning";
  }

  return "status-info";
}

function prettyJson(value: any) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function getLogTime(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
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

function FieldCard({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
      <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
        {label}
      </p>

      <div
        className={cn(
          "mt-2 break-words text-sm font-semibold text-[var(--text-strong)]",
          mono && "font-mono text-xs"
        )}
      >
        {value}
      </div>
    </div>
  );
}

function SectionHeader({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-soft)] text-[var(--accent)]">
          {icon}
        </div>

        <div>
          <h2 className="text-lg font-black text-[var(--text-strong)]">
            {title}
          </h2>

          {description && (
            <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
              {description}
            </p>
          )}
        </div>
      </div>

      {action}
    </div>
  );
}

function WorkflowTimelineSection({ run }: { run: WorkflowRun }) {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<Clock className="h-4 w-4" />}
        title="Workflow Timeline"
        description="Created, updated, completed, and duration metadata for this run."
      />

      <div className="grid gap-3 md:grid-cols-4">
        <FieldCard label="Created" value={formatDateTime(run.created_at)} />
        <FieldCard label="Updated" value={formatDateTime(run.updated_at)} />
        <FieldCard label="Completed" value={formatDateTime(run.completed_at)} />
        <FieldCard label="Duration" value={getWorkflowDuration(run)} />
      </div>
    </section>
  );
}

function ApprovalRequiredPanel({
  run,
  approvalProcessing,
  approvalLoading,
  rejectionLoading,
  deleteLoading,
  onApprove,
  onReject,
}: {
  run: WorkflowRun;
  approvalProcessing: boolean;
  approvalLoading: boolean;
  rejectionLoading: boolean;
  deleteLoading: boolean;
  onApprove: () => Promise<void>;
  onReject: () => Promise<void>;
}) {
  if (!isWaitingForApproval(run)) {
    return null;
  }

  const actionLoading = approvalLoading || rejectionLoading;
  const approvalButtonsDisabled = approvalProcessing || actionLoading || deleteLoading;

  return (
    <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--warning)_34%,transparent)] bg-[var(--warning-soft)] p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-black text-[var(--warning)]">
            {approvalProcessing ? (
              <Clock className="h-4 w-4" />
            ) : (
              <ShieldCheck className="h-4 w-4" />
            )}
            {approvalProcessing ? "Approval is being processed" : "Approval Required"}
          </h3>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
            {approvalProcessing
              ? "AIRA-X is already processing this approval-gated action. Controls are disabled to prevent duplicate execution."
              : "This workflow is paused before a risky action. Approve to continue, or reject to stop safely."}
          </p>

          {run.pending_action && (
            <p className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-3 text-sm text-[var(--text)]">
              <strong className="text-[var(--text-strong)]">Pending action:</strong>{" "}
              {run.pending_action}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onApprove}
            disabled={approvalButtonsDisabled}
            className="rounded-xl bg-[var(--warning)] px-5 py-3 text-sm font-black text-white shadow-[var(--shadow-soft)] transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            {approvalProcessing
              ? "Processing..."
              : approvalLoading
                ? "Approving..."
                : "Approve & Continue"}
          </button>

          <button
            type="button"
            onClick={onReject}
            disabled={approvalButtonsDisabled}
            className="inline-flex items-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-black text-[var(--danger)] transition hover:bg-[var(--danger-soft)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <XCircle className="h-4 w-4" />
            {approvalProcessing
              ? "Processing..."
              : rejectionLoading
                ? "Rejecting..."
                : "Reject Action"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ApprovalResolutionSection({ run }: { run: WorkflowRun }) {
  const resolution = getApprovalResolution(run);

  if (!resolution) {
    return null;
  }

  const status = resolution.status || "unknown";

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<ShieldAlert className="h-4 w-4" />}
        title="Approval Resolution"
        description="How the approval-gated action was handled."
        action={
          <RunBadge className={getStatusClass(status)}>
            {getStatusIcon(status)}
            {getApprovalResolutionLabel(status)}
          </RunBadge>
        }
      />

      {status === "stale_processing_recovered" && (
        <div className="mb-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm leading-6 text-[var(--danger)]">
          <strong>Stale approval recovered:</strong> AIRA-X detected approval
          processing stayed active for too long and stopped the workflow safely
          to prevent duplicate execution.
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <FieldCard label="Resolution Status" value={status} />
        <FieldCard
          label="Approval Action"
          value={resolution.action || run.pending_action || "No action recorded"}
        />
        <FieldCard
          label="Requested"
          value={formatDateTime(resolution.requested_at)}
        />
        <FieldCard
          label="Completed"
          value={formatDateTime(resolution.completed_at)}
        />
        <FieldCard
          label="Final Status"
          value={resolution.final_status || run.status || "Not recorded"}
        />
        <FieldCard
          label="Final Decision"
          value={resolution.final_decision || run.decision || "Not recorded"}
        />
      </div>

      {resolution.error && (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm leading-6 text-[var(--danger)]">
          <strong>Error:</strong> {resolution.error}
        </div>
      )}
    </section>
  );
}

function GitWritePreflightSection({ context }: { context: ApprovalContext }) {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<GitBranch className="h-4 w-4" />}
        title="Git Write Preflight"
        description="Repository context captured before a Git write action."
        action={
          <RunBadge className="status-warning">
            <ShieldAlert className="h-3.5 w-3.5" />
            Approval gated
          </RunBadge>
        }
      />

      <div className="grid gap-3 md:grid-cols-2">
        <FieldCard label="Current Branch" value={context.branch || "Unknown"} />
        <FieldCard
          label="Git Action"
          value={context.pending_action || "Unknown action"}
        />
      </div>

      {context.commit_message && (
        <div className="mt-3">
          <FieldCard label="Commit Message" value={context.commit_message} />
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Changed Files
          </p>

          <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.changed_files?.trim() || "No changed files detected."}
          </pre>
        </div>

        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Diff Summary
          </p>

          <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.diff_summary?.trim() || "No diff summary available."}
          </pre>
        </div>
      </div>
    </section>
  );
}

function GitPushPreflightSection({ context }: { context: ApprovalContext }) {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<UploadCloud className="h-4 w-4" />}
        title="Git Push Preflight"
        description="Remote push context captured before modifying the remote repository."
        action={
          <RunBadge className="status-danger">
            <UploadCloud className="h-3.5 w-3.5" />
            Remote write
          </RunBadge>
        }
      />

      <div className="grid gap-3 md:grid-cols-4">
        <FieldCard label="Target Remote" value={context.target_remote || "origin"} />
        <FieldCard
          label="Target Branch"
          value={context.target_branch || context.branch || "Unknown"}
        />
        <FieldCard label="Current Branch" value={context.branch || "Unknown"} />
        <FieldCard
          label="Git Action"
          value={context.pending_action || "Unknown action"}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Branch Tracking Status
          </p>

          <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.status_branch?.trim() ||
              "No branch tracking status available."}
          </pre>
        </div>

        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Remote Info
          </p>

          <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.remote_info?.trim() || "No remote info available."}
          </pre>
        </div>

        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Latest Local Commit
          </p>

          <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.last_commit?.trim() || "No latest commit available."}
          </pre>
        </div>

        <div>
          <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
            Recent Local Commits
          </p>

          <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
            {context.recent_commits?.trim() || "No recent commits available."}
          </pre>
        </div>
      </div>
    </section>
  );
}

function ApprovalContextSection({ run }: { run: WorkflowRun }) {
  const context = getApprovalContext(run);

  if (!context) {
    return null;
  }

  if (context.type === "git_write_preflight") {
    return <GitWritePreflightSection context={context} />;
  }

  if (context.type === "git_push_preflight") {
    return <GitPushPreflightSection context={context} />;
  }

  return null;
}

function CleanupActionsSection({ run }: { run: WorkflowRun }) {
  const cleanupActions = getCleanupActions(run);

  if (cleanupActions.length === 0) {
    return null;
  }

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<CheckCircle2 className="h-4 w-4" />}
        title="Cleanup Actions"
        description="Cleanup performed after rejection, failure, or workflow stop conditions."
        action={
          <RunBadge className="status-success">
            {cleanupActions.length} action{cleanupActions.length === 1 ? "" : "s"}
          </RunBadge>
        }
      />

      <div className="space-y-3">
        {cleanupActions.map((cleanup: any, index: number) => (
          <div
            key={`${cleanup.tool_action}-${index}`}
            className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
          >
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <RunBadge
                className={
                  cleanup.result?.success ? "status-success" : "status-danger"
                }
              >
                {cleanup.result?.success ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {cleanup.result?.success ? "Successful" : "Failed"}
              </RunBadge>

              <RunBadge className="border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)]">
                {cleanup.tool_name}:{cleanup.tool_action}
              </RunBadge>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <FieldCard label="Reason" value={cleanup.reason || "Not recorded"} />
              <FieldCard
                label="Command"
                value={cleanup.result?.command || "No command recorded"}
                mono
              />
            </div>

            {(cleanup.result?.output || cleanup.result?.error) && (
              <pre className="mt-4 max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
                {cleanup.result?.output || cleanup.result?.error}
              </pre>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function ExecutionPlanSection({ steps }: { steps: WorkflowStep[] }) {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<ListChecks className="h-4 w-4" />}
        title="Execution Plan"
        description="Step-by-step plan, assigned agents, tool actions, results, and failures."
        action={
          <RunBadge className="status-info">
            {steps.length} step{steps.length === 1 ? "" : "s"}
          </RunBadge>
        }
      />

      {steps.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-8 text-center">
          <p className="text-sm text-[var(--text-muted)]">
            No execution plan recorded.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {steps.map((step) => (
            <article
              key={step.id}
              className="relative rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-5"
            >
              <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] font-mono text-xs font-black text-[var(--text-strong)]">
                    {step.id}
                  </div>

                  <div>
                    <h3 className="text-base font-black text-[var(--text-strong)]">
                      {step.title}
                    </h3>

                    <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
                      {step.description}
                    </p>
                  </div>
                </div>

                <RunBadge className={getStepStatusClass(step.status)}>
                  {getStatusIcon(step.status)}
                  {step.status}
                </RunBadge>
              </div>

              <div className="grid gap-3 md:grid-cols-4">
                <FieldCard label="Agent" value={step.assigned_agent || "Unassigned"} />
                <FieldCard label="Tool" value={step.tool_name || "No tool"} />
                <FieldCard label="Action" value={step.tool_action || "No action"} />
                <FieldCard
                  label="Payload"
                  value={
                    step.tool_payload && Object.keys(step.tool_payload).length > 0
                      ? "Available"
                      : "Empty"
                  }
                />
              </div>

              {step.result && (
                <div className="mt-4">
                  <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
                    Result
                  </p>

                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
                    {step.result}
                  </pre>
                </div>
              )}

              {step.error && (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm leading-6 text-[var(--danger)]">
                  <strong>Error:</strong> {step.error}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function WorkflowLogsSection({ logs }: { logs?: WorkflowLog[] }) {
  if (!logs || logs.length === 0) {
    return null;
  }

  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<History className="h-4 w-4" />}
        title="Workflow Logs"
        description="Chronological trace events emitted by the workflow and agent layers."
        action={
          <RunBadge className="status-info">
            {logs.length} log{logs.length === 1 ? "" : "s"}
          </RunBadge>
        }
      />

      <div className="space-y-3">
        {logs.map((log, index) => (
          <article
            key={`${log.timestamp}-${index}`}
            className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-black text-[var(--text-strong)]">
                  {log.agent}
                </p>

                <p className="mt-1 text-xs font-semibold text-[var(--text-muted)]">
                  Event: {log.event}
                </p>
              </div>

              <p className="font-mono text-[11px] text-[var(--text-subtle)]">
                {getLogTime(log.timestamp)}
              </p>
            </div>

            <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-[11px] leading-5">
              {prettyJson(log.details)}
            </pre>
          </article>
        ))}
      </div>
    </section>
  );
}

function RawExecutionOutputsSection({ outputs }: { outputs: any[] }) {
  return (
    <section className="sarvam-card rounded-[1.5rem] p-5">
      <SectionHeader
        icon={<TerminalSquare className="h-4 w-4" />}
        title="Raw Execution Outputs"
        description="Complete tool execution payloads captured for audit and debugging."
        action={
          <RunBadge className="status-info">
            {outputs.length} output{outputs.length === 1 ? "" : "s"}
          </RunBadge>
        }
      />

      {outputs.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-8 text-center">
          <p className="text-sm text-[var(--text-muted)]">
            No execution outputs recorded.
          </p>
        </div>
      ) : (
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl p-4 text-xs leading-6">
          {prettyJson(outputs)}
        </pre>
      )}
    </section>
  );
}

export default function WorkflowDetailPage() {
  const params = useParams();
  const router = useRouter();
  const runIdParam = params?.run_id;
  const runId = Array.isArray(runIdParam) ? runIdParam[0] : runIdParam;

  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [rejectionLoading, setRejectionLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");

  const loadRun = useCallback(
    async (options?: { showLoading?: boolean }) => {
      if (!runId) {
        setError("Workflow run ID is missing.");
        setRun(null);
        setLoading(false);
        return;
      }

      const showLoading = options?.showLoading ?? true;

      try {
        if (showLoading) {
          setLoading(true);
        }

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
        if (showLoading) {
          setLoading(false);
        }
      }
    },
    [runId]
  );

  async function handleApprove() {
    if (!run?.run_id || isApprovalProcessing(run)) return;

    setApprovalLoading(true);
    setError("");

    try {
      const updatedRun = await approveAiraX(run.run_id);
      setRun(updatedRun);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to approve workflow.";

      setError(message);
      await loadRun({ showLoading: false });
    } finally {
      setApprovalLoading(false);
    }
  }

  async function handleReject() {
    if (!run?.run_id || isApprovalProcessing(run)) return;

    setRejectionLoading(true);
    setError("");

    try {
      const updatedRun = await rejectAiraX(run.run_id);
      setRun(updatedRun);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to reject workflow.";

      setError(message);
      await loadRun({ showLoading: false });
    } finally {
      setRejectionLoading(false);
    }
  }

  async function handleDelete() {
    if (!run?.run_id || isApprovalProcessing(run) || deleteLoading) return;

    const confirmed = window.confirm(
      `Delete this workflow run from history?\n\n${run.user_goal}\n\nThis only removes the saved run record.`
    );

    if (!confirmed) {
      return;
    }

    setDeleteLoading(true);
    setError("");

    try {
      await deleteAiraXRun(run.run_id);
      router.push("/workflows");
      router.refresh();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to delete workflow run.";

      setError(message);
      await loadRun({ showLoading: false });
    } finally {
      setDeleteLoading(false);
    }
  }

  useEffect(() => {
    loadRun();
  }, [loadRun]);

  const approvalProcessing = isApprovalProcessing(run);
  const actionLoading = approvalLoading || rejectionLoading;
  const deleteButtonDisabled =
    approvalProcessing || actionLoading || deleteLoading;

  const approvalResolution = useMemo(
    () => (run ? getApprovalResolution(run) : null),
    [run]
  );

  const cleanupActions = useMemo(
    () => (run ? getCleanupActions(run) : []),
    [run]
  );

  const summaryCards = useMemo(() => {
    if (!run) {
      return [];
    }

    return [
      {
        label: "Decision",
        value: run.decision || "Not recorded",
      },
      {
        label: "Steps",
        value: String(run.plan.length),
      },
      {
        label: "Logs",
        value: String(run.workflow_logs?.length || 0),
      },
      {
        label: "Cleanup",
        value: cleanupActions.length
          ? `${cleanupActions.length} action(s)`
          : "None",
      },
    ];
  }, [cleanupActions.length, run]);

  useEffect(() => {
    if (!approvalProcessing) {
      setPolling(false);
      return;
    }

    setPolling(true);

    const intervalId = window.setInterval(() => {
      loadRun({ showLoading: false });
    }, 2000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [approvalProcessing, loadRun]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

        <div className="relative z-10">
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <Link
              href="/workflows"
              className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Workflow Runs
            </Link>

            <Link
              href="/chat"
              className="inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-3 py-1.5 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
            >
              <TerminalSquare className="h-3.5 w-3.5" />
              Open Execute Panel
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>

            <Link
              href="/approvals"
              className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Review Approvals
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <div>
              <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
                <Workflow className="h-3.5 w-3.5" />
                AIRA-X Workflow Detail
              </div>

              <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
                Workflow Run
              </h1>

              <p className="mt-3 max-w-3xl break-all font-mono text-xs leading-6 text-[var(--text-subtle)]">
                {runId}
              </p>

              {run && (
                <p className="mt-4 max-w-4xl text-lg font-black leading-7 text-[var(--text-strong)]">
                  {run.user_goal}
                </p>
              )}

              {run?.final_answer && (
                <p className="mt-3 max-w-4xl text-sm leading-7 text-[var(--text-muted)]">
                  {run.final_answer}
                </p>
              )}

              {polling && (
                <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--border-strong)] bg-[var(--accent-soft)] px-3 py-1.5 text-xs font-black text-[var(--accent)]">
                  <Activity className="h-3.5 w-3.5" />
                  Auto-refreshing approval processing
                </div>
              )}
            </div>

            {run && (
              <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <RunBadge className={getStatusClass(run.status)}>
                    {getStatusIcon(run.status)}
                    {run.status}
                  </RunBadge>

                  {approvalResolution && (
                    <RunBadge className={getStatusClass(approvalResolution.status)}>
                      <ShieldAlert className="h-3.5 w-3.5" />
                      {getApprovalResolutionLabel(approvalResolution.status)}
                    </RunBadge>
                  )}
                </div>

                <div className="grid gap-3">
                  {summaryCards.map((card) => (
                    <FieldCard
                      key={card.label}
                      label={card.label}
                      value={card.value}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading workflow run...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && run && (
        <>
          <section className="sarvam-card rounded-[1.5rem] p-5">
            <SectionHeader
              icon={<Wrench className="h-4 w-4" />}
              title="Run Controls"
              description="Approval and maintenance controls for this workflow run."
            />

            <ApprovalRequiredPanel
              run={run}
              approvalProcessing={approvalProcessing}
              approvalLoading={approvalLoading}
              rejectionLoading={rejectionLoading}
              deleteLoading={deleteLoading}
              onApprove={handleApprove}
              onReject={handleReject}
            />

            {!isWaitingForApproval(run) && (
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
                <p className="text-sm font-black text-[var(--text-strong)]">
                  No approval action is currently pending.
                </p>

                <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
                  This run can be inspected or removed from local workflow
                  history when no longer needed.
                </p>

                <Link
                  href="/workflows"
                  className="mt-3 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                >
                  View all workflow runs
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            )}

            <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <h3 className="text-sm font-black text-[var(--text-strong)]">
                    History Maintenance
                  </h3>

                  <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">
                    Delete this saved workflow run from local history after you
                    no longer need it.
                  </p>

                  {approvalProcessing && (
                    <p className="mt-2 text-xs font-black text-[var(--warning)]">
                      Deletion is disabled while approval processing is active.
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteButtonDisabled}
                  className="inline-flex w-fit items-center gap-2 rounded-xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] px-5 py-3 text-sm font-black text-[var(--danger)] transition hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deleteLoading ? (
                    <RefreshCw className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  {deleteLoading ? "Deleting..." : "Delete Run"}
                </button>
              </div>
            </div>
          </section>

          <WorkflowTimelineSection run={run} />
          <ApprovalResolutionSection run={run} />
          <ApprovalContextSection run={run} />
          <CleanupActionsSection run={run} />
          <ExecutionPlanSection steps={run.plan} />
          <WorkflowLogsSection logs={run.workflow_logs} />
          <RawExecutionOutputsSection outputs={run.execution_outputs} />
        </>
      )}
    </div>
  );
}
