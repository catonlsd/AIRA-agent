"use client";

import {
  useCallback,
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
  FileText,
  FileUp,
  GitBranch,
  HelpCircle,
  Library,
  Paperclip,
  Search,
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
import { TechnicalDetailsPanel } from "@/components/technical-details";
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
import { getSessionId } from "@/lib/session";
import { isWorkflowResult, type FinalLike } from "@/lib/turn-routing";
import {
  describeRuntimeAction,
  presentArtifact,
  presentExecutionPhases,
  provenanceLabel,
  summarizeEvidence,
  type ArtifactView,
  type ExecutionPhase,
} from "@/lib/execution-presenter";
import {
  livePhaseForMode,
  livePhaseForStage,
  type LivePhase,
} from "@/lib/live-phase-presenter";
import { takeContinuation } from "@/lib/runs";
import {
  clearContext,
  contextLabel,
  createBundle,
  fetchContext,
  itemsSummary,
  removeContextItem,
  type AttachedContext,
} from "@/lib/chat-context";

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
  current_step?: number | null;
  requires_approval?: boolean;
  pending_action?: string;
  approval_context?: ApprovalContext | null;
  plan: AiraXStep[];
  execution_outputs: any[];
  memory: any;
  workflow_logs?: WorkflowLog[];
};

// ─── Octa — the AIRA-X Supervisor mascot ─────────────────────────────────────
// A premium pixel cyber-octopus: one intelligent core, many capabilities. Octa
// is state-aware and mirrors the live supervisor state (idle → thinking →
// researching/reading/executing → approval → success/error). Pure SVG + CSS;
// brand colors (#6EC1FF / #AEE4FF / #00D4FF); gentle motion only. Theme-aware
// (cyan glow in dark, soft blue in light) and honors prefers-reduced-motion.

// Octa is the visible state of the AssistantSupervisor — not a second assistant.
// Every value here is a SUPERVISOR STATE, never an identity or capability claim.
type OctaState =
  | "idle"
  | "routing"
  | "thinking"
  | "researching"
  | "reading"
  | "memory"
  | "executing"
  | "approval"
  | "clarify"
  | "success"
  | "error";

const OCTA_STATUS: Record<OctaState, { label: string; Icon: typeof Sparkles }> = {
  idle:        { label: "Ready",                       Icon: Sparkles },
  routing:     { label: "Routing your request…",       Icon: GitBranch },
  thinking:    { label: "Thinking…",                   Icon: Activity },
  researching: { label: "Researching sources…",        Icon: Search },
  reading:     { label: "Reading uploaded documents…", Icon: FileText },
  memory:      { label: "Retrieving memory…",          Icon: Database },
  executing:   { label: "Executing workflow…",         Icon: Workflow },
  approval:    { label: "Waiting for approval…",        Icon: ShieldAlert },
  clarify:     { label: "Waiting for details…",          Icon: HelpCircle },
  success:     { label: "Task completed.",              Icon: CheckCircle2 },
  error:       { label: "Something went wrong.",        Icon: XCircle },
};

// Tiny idle gestures Octa plays at random while it's just sitting there.
const OCTA_MICROS = ["blink", "curl", "look"] as const;

// Human-readable supervisor path names for the inspector (trace awareness).
const OCTA_PATHS: Record<string, string> = {
  general_chat: "Chat Path",
  self_memory: "Memory Path",
  web_research: "Research Path",
  document_qa: "Document Path",
  execution: "Execution Path",
  research_then_execution: "Execution Path",
};

// Live supervisor facts surfaced in the inspector. All values are real system
// state — nothing simulated.
type OctaInspectorData = {
  lastRoute: string | null;
  runId: string | null;
  documentsIndexed: number;
  memoryActive: boolean;
  sessionId: string;
  lastLatencyMs: number | null;
};

/** Map a supervisor routing mode to an Octa working-state. */
function octaStateForMode(mode: string): OctaState {
  if (mode === "web_research") return "researching";
  if (mode === "document_qa") return "reading";
  if (mode === "self_memory") return "memory";
  if (mode === "execution" || mode === "research_then_execution") return "executing";
  return "thinking";
}

/** The pixel cyber-octopus itself. State drives CSS via the wrapper attribute. */
function Octa({ micro }: { micro?: string | null }) {
  return (
    <svg
      className="octa-svg"
      viewBox="0 0 48 48"
      role="img"
      aria-label="Octa, the AIRA-X assistant"
      shapeRendering="crispEdges"
      data-micro={micro || undefined}
    >
      {/* antenna */}
      <rect className="o-head" x="23" y="3" width="2" height="5" />
      <rect className="o-eye o-pulse" x="22" y="1" width="4" height="3" />

      {/* mantle / dome */}
      <rect className="o-head" x="18" y="7" width="12" height="2" />
      <rect className="o-head" x="15" y="9" width="18" height="2" />
      <rect className="o-head" x="13" y="11" width="22" height="2" />
      <rect className="o-head" x="12" y="13" width="24" height="11" />
      <rect className="o-head" x="13" y="24" width="22" height="2" />
      {/* top-left sheen */}
      <rect className="o-head-hi" x="16" y="9" width="5" height="2" />
      <rect className="o-head-hi" x="14" y="11" width="5" height="2" />
      <rect className="o-head-hi" x="13" y="13" width="3" height="3" />
      {/* under-shade + circuit accents */}
      <rect className="o-head-lo" x="12" y="22" width="24" height="2" />
      <rect className="o-accent" x="30" y="12" width="1" height="1" />
      <rect className="o-accent" x="32" y="15" width="1" height="1" />
      <rect className="o-accent" x="29" y="20" width="1" height="1" />

      {/* visor eye-strip */}
      <rect className="o-visor" x="14" y="15" width="20" height="5" />
      <g className="o-eyes">
        <rect className="o-eye o-blink" x="18" y="16" width="4" height="3" />
        <rect className="o-eye o-blink" x="26" y="16" width="4" height="3" />
      </g>
      {/* scan line (active states) */}
      <rect className="o-scan" x="14" y="15" width="1" height="5" />

      {/* tentacles */}
      <g className="o-arm-grp o-arm-1">
        <rect className="o-arm-lo" x="13" y="25" width="3" height="4" />
        <rect className="o-arm-lo" x="12" y="29" width="3" height="2" />
      </g>
      <g className="o-arm-grp o-arm-2">
        <rect className="o-arm" x="17" y="26" width="3" height="5" />
        <rect className="o-arm" x="16" y="31" width="3" height="2" />
      </g>
      <g className="o-arm-grp o-arm-3">
        <rect className="o-arm" x="22" y="26" width="4" height="6" />
        <rect className="o-arm" x="22" y="32" width="4" height="2" />
      </g>
      <g className="o-arm-grp o-arm-4">
        <rect className="o-arm" x="28" y="26" width="3" height="5" />
        <rect className="o-arm" x="29" y="31" width="3" height="2" />
      </g>
      <g className="o-arm-grp o-arm-5">
        <rect className="o-arm-lo" x="32" y="25" width="3" height="4" />
        <rect className="o-arm-lo" x="33" y="29" width="3" height="2" />
      </g>
    </svg>
  );
}

/**
 * OctaStatus — the single visual status system for the AssistantSupervisor.
 * Octa + a connected status bubble; it SIGNALS supervisor state, it is not a
 * second assistant. Sits ABOVE the composer (never inside it). `size` "lg"
 * stacks vertically (home stage); "sm" is a compact inline row (in-chat).
 * `message` shows a transient, event-driven supervisor message; `progress`
 * appends real workflow progress (never simulated). Single click → visual
 * reaction only (it never writes into the composer). Double-click or the info
 * button opens the Supervisor Inspector (read-only system facts).
 */
function OctaStatus({
  state,
  message,
  progress,
  size = "lg",
  className,
  inspector,
}: {
  state: OctaState;
  message?: string;
  progress?: string | null;
  size?: "lg" | "sm";
  className?: string;
  inspector?: OctaInspectorData;
}) {
  const status = OCTA_STATUS[state];
  const Icon = status.Icon;
  const [puffKey, setPuffKey] = useState(0);
  const [reacting, setReacting] = useState(false);
  const [micro, setMicro] = useState<(typeof OCTA_MICROS)[number] | null>(null);
  const [showInspector, setShowInspector] = useState(false);
  const reactTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (reactTimerRef.current) clearTimeout(reactTimerRef.current);
  }, []);

  // Esc dismisses the inspector.
  useEffect(() => {
    if (!showInspector) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowInspector(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showInspector]);

  // Single click → visual feedback only (squish + ink puff). Octa never writes
  // into the composer and never suggests tasks.
  const handlePoke = () => {
    setPuffKey((k) => k + 1);
    if (reactTimerRef.current) clearTimeout(reactTimerRef.current);
    setReacting(false);
    requestAnimationFrame(() => {
      setReacting(true);
      reactTimerRef.current = setTimeout(() => setReacting(false), 520);
    });
  };

  // Idle micro-moments: only while idle, every 12–18s, play one tiny gesture.
  useEffect(() => {
    if (state !== "idle") return;
    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    let alive = true;
    let waitTimer: ReturnType<typeof setTimeout>;
    let clearTimer: ReturnType<typeof setTimeout>;

    const schedule = () => {
      waitTimer = setTimeout(() => {
        if (!alive) return;
        const pick = OCTA_MICROS[Math.floor(Math.random() * OCTA_MICROS.length)];
        setMicro(pick);
        clearTimer = setTimeout(() => {
          if (!alive) return;
          setMicro(null);
          schedule();
        }, 1400);
      }, 12000 + Math.random() * 6000);
    };
    schedule();

    return () => {
      alive = false;
      clearTimeout(waitTimer);
      clearTimeout(clearTimer);
      setMicro(null);
    };
  }, [state]);

  const label = message ?? status.label;
  const activeRoute = state !== "idle" && state !== "success" && state !== "error";

  return (
    <div
      className={cn("octa-companion", `octa-companion--${size}`, className)}
      data-octa-state={state}
      aria-live="polite"
    >
      <span className="octa-figure-wrap">
        <button
          type="button"
          className={cn("octa-figure", reacting && "octa-figure--poke")}
          onClick={handlePoke}
          onDoubleClick={() => inspector && setShowInspector((v) => !v)}
          aria-label="AIRA-X supervisor status"
        >
          {puffKey > 0 && <span key={puffKey} className="octa-ink" aria-hidden="true" />}
          <Octa micro={micro} />
        </button>
        {/* route badge — which path the supervisor is on right now */}
        {activeRoute && (
          <span className="octa-route-badge" aria-hidden="true">
            <Icon className="octa-route-badge-icon" />
          </span>
        )}
        {inspector && showInspector && (
          <div className="octa-inspector" role="dialog" aria-label="Supervisor status">
            <div className="octa-inspector-head">
              <span>Supervisor Status</span>
              <button
                type="button"
                className="octa-inspector-close"
                onClick={() => setShowInspector(false)}
                aria-label="Close inspector"
              >
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </div>
            {/* current supervisor state — visually dominant, from real state only */}
            <p className="octa-inspector-status">
              <span className="octa-inspector-status-dot" aria-hidden="true" />
              {status.label}
            </p>
            <dl className="octa-inspector-grid">
              <dt>Mode</dt><dd>{inspector.lastRoute ? (OCTA_PATHS[inspector.lastRoute] ?? inspector.lastRoute).replace(/ Path$/, "") : "Idle"}</dd>
              <dt>Memory</dt><dd>{inspector.memoryActive ? "Active" : "No stored context"}</dd>
              <dt>Documents</dt><dd>{inspector.documentsIndexed} indexed</dd>
            </dl>
          </div>
        )}
      </span>
      <span className="octa-bubble-row">
        {/* keyed by state + event message so the entrance pulse replays on each
            supervisor transition. */}
        <div key={`${state}|${message ?? ""}`} className="octa-bubble" role="status">
          <span className="octa-bubble-dot" aria-hidden="true" />
          <Icon className="octa-bubble-icon" aria-hidden="true" />
          <span className="octa-bubble-label">
            {label}
            {progress ? <span className="octa-bubble-progress"> {progress}</span> : null}
          </span>
        </div>
        {inspector && (
          <button
            type="button"
            className="octa-info-btn"
            onClick={() => setShowInspector((v) => !v)}
            aria-label="Toggle supervisor inspector"
            aria-expanded={showInspector}
          >
            i
          </button>
        )}
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
          <p className="mt-0.5 type-body-sm text-[var(--text-muted)]">{description}</p>
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
        <p className="mb-2 type-label text-[var(--text-subtle)]">Changed Files</p>
        <CodeBlock value={context.changed_files} fallback="No changed files detected." />
      </div>
      <div className="mt-3">
        <p className="mb-2 type-label text-[var(--text-subtle)]">Diff Summary</p>
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
          <p className="mb-2 type-label text-[var(--text-subtle)]">{label}</p>
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


// ─── Turn Card ────────────────────────────────────────────────────────────────

// ─── Clarification option cards ──────────────────────────────────────────────
// When the supervisor needs details it returns a structured clarification
// payload (plus a readable text fallback). These cards make the options
// clickable: one selection per question, custom values via a small input, and
// a Continue button that submits the structured reply back to the supervisor.

type ClarificationOption = { id: string; label: string; value: string };
type ClarificationQuestion = {
  id: string;
  title: string;
  required: boolean;
  options: ClarificationOption[];
};
type ClarificationData = {
  required: boolean;
  original_request: string;
  questions: ClarificationQuestion[];
};

function isClarificationData(value: unknown): value is ClarificationData {
  if (!value || typeof value !== "object") return false;
  const data = value as ClarificationData;
  return Array.isArray(data.questions) && data.questions.length > 0;
}

function ClarificationCard({
  data,
  busy,
  onSubmit,
}: {
  data: ClarificationData;
  busy: boolean;
  onSubmit: (text: string) => void;
}) {
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [customValues, setCustomValues] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);

  const disabled = busy || submitted;

  const answeredValue = (q: ClarificationQuestion): string | null => {
    const picked = selections[q.id];
    if (!picked) return null;
    if (picked === "custom") {
      const custom = (customValues[q.id] || "").trim();
      return custom ? custom : null;
    }
    return picked;
  };

  const allAnswered = data.questions.every((q) => !q.required || answeredValue(q) !== null);

  const handleContinue = () => {
    if (!allAnswered || disabled) return;
    const lines = [
      "Clarification response:",
      `Original request: ${data.original_request}`,
    ];
    for (const q of data.questions) {
      const value = answeredValue(q);
      if (value) lines.push(`${q.title}: ${value}`);
    }
    setSubmitted(true);
    onSubmit(lines.join("\n"));
  };

  return (
    <div className="clarify-card">
      <p className="clarify-intro">Choose the setup so I build the right thing:</p>

      {data.questions.map((q) => (
        <div key={q.id} className="clarify-section">
          <p className="clarify-section-title">{q.title}</p>
          <div className="clarify-options">
            {q.options.map((option) => {
              const selected = selections[q.id] === option.value;
              return (
                <button
                  key={option.id}
                  type="button"
                  disabled={disabled}
                  className={cn("clarify-option", selected && "clarify-option--selected")}
                  aria-pressed={selected}
                  onClick={() =>
                    setSelections((prev) => ({ ...prev, [q.id]: option.value }))
                  }
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {selections[q.id] === "custom" && (
            <input
              type="text"
              value={customValues[q.id] || ""}
              disabled={disabled}
              onChange={(e) =>
                setCustomValues((prev) => ({ ...prev, [q.id]: e.target.value }))
              }
              placeholder={`Describe your custom ${q.title.toLowerCase()}…`}
              className="clarify-custom-input"
            />
          )}
        </div>
      ))}

      <button
        type="button"
        className="clarify-continue"
        disabled={!allAnswered || disabled}
        onClick={handleContinue}
      >
        {submitted ? "Continuing…" : "Continue with selected setup"}
      </button>
    </div>
  );
}

// ─── Plan approval actions ───────────────────────────────────────────────────
// Rendered under a plan-ready reply: approving immediately resumes the run into
// real tool execution on the backend (no typing "approve plan" needed).

function PlanApprovalActions({
  busy,
  onDecide,
}: {
  busy: boolean;
  onDecide: (text: string) => void;
}) {
  const [choice, setChoice] = useState<"approve" | "reject" | null>(null);
  const disabled = busy || choice !== null;

  return (
    <div className="plan-approval-row">
      <button
        type="button"
        className="clarify-continue"
        disabled={disabled}
        onClick={() => {
          setChoice("approve");
          onDecide("approve plan");
        }}
      >
        {choice === "approve" ? "Executing…" : "Approve plan & execute"}
      </button>
      <button
        type="button"
        className="plan-reject-btn"
        disabled={disabled}
        onClick={() => {
          setChoice("reject");
          onDecide("reject");
        }}
      >
        Reject
      </button>
    </div>
  );
}

// ─── Premium execution UX ─────────────────────────────────────────────────────
// Presentation components for the guided execution flow: a minimal phase
// stepper, a meaningful runtime-approval card, and compact evidence chips.
// All labels come from the presenter layer — never raw backend enums.

function ExecutionProgress({ phases }: { phases: ExecutionPhase[] }) {
  return (
    <div className="exec-progress" aria-label="Execution progress">
      {phases.map((phase) => (
        <span key={phase.key} className={cn("exec-phase", `exec-phase--${phase.state}`)}>
          <span className="exec-phase-dot" aria-hidden="true" />
          {phase.label}
        </span>
      ))}
    </div>
  );
}

function RuntimeApprovalCard({
  actions,
  busy,
  onDecide,
}: {
  actions: Array<{ type?: string; description?: string; payload?: { command?: string } }>;
  busy: boolean;
  onDecide: (text: string) => void;
}) {
  const [choice, setChoice] = useState<"approve" | "reject" | null>(null);
  const disabled = busy || choice !== null;

  return (
    <div className="runtime-approval-card">
      <p className="runtime-approval-title">Validate the generated project?</p>
      <p className="runtime-approval-sub">
        Your files are written. With your approval, AIRA-X will run these checks
        and repair issues it finds — approval is needed because they run real
        commands on your machine.
      </p>
      <ul className="runtime-approval-list">
        {actions.map((action, index) => (
          <li key={index}>{describeRuntimeAction(action)}</li>
        ))}
      </ul>
      <details className="runtime-approval-details">
        <summary>Show exact commands</summary>
        <pre>{actions.map((a) => a.payload?.command ?? "").filter(Boolean).join("\n")}</pre>
      </details>
      <div className="plan-approval-row">
        <button
          type="button"
          className="clarify-continue"
          disabled={disabled}
          onClick={() => {
            setChoice("approve");
            onDecide("approve");
          }}
        >
          {choice === "approve" ? "Validating…" : "Run validation"}
        </button>
        <button
          type="button"
          className="plan-reject-btn"
          disabled={disabled}
          onClick={() => {
            setChoice("reject");
            onDecide("reject");
          }}
        >
          Skip — keep files as-is
        </button>
      </div>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: ArtifactView }) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const href = artifact.downloadUrl ? `${apiBase}${artifact.downloadUrl}` : null;
  const icon =
    artifact.type === "PPTX" ? FileText : artifact.type === "XLSX" ? Database : FileText;
  const Icon = icon;
  return (
    <div className="artifact-card">
      <span className="artifact-icon" aria-hidden="true">
        <Icon className="h-5 w-5" />
      </span>
      <div className="artifact-body">
        <p className="artifact-title">{artifact.title}</p>
        {artifact.subtitle && <p className="artifact-subtitle">{artifact.subtitle}</p>}
        <p className="artifact-meta">
          {artifact.type} · {artifact.summary}
          {artifact.imageNote && <span> · {artifact.imageNote}</span>}
          {artifact.sizeLabel && <span> · {artifact.sizeLabel}</span>}
          {artifact.validated && <span className="artifact-valid"> · ✓ validated</span>}
        </p>
        <p className="artifact-loc">
          {artifact.theme && <span>{artifact.theme} theme · </span>}
          {artifact.saveLocation}
        </p>
        {artifact.externalNote && <p className="artifact-note">{artifact.externalNote}</p>}
      </div>
      {href && (
        <a className="artifact-download" href={href} download={artifact.filename}>
          Download
        </a>
      )}
    </div>
  );
}

function EvidenceStrip({ chips }: { chips: ReturnType<typeof summarizeEvidence> }) {
  if (chips.length === 0) return null;
  return (
    <div className="evidence-strip" aria-label="Execution evidence">
      {chips.map((chip, index) => (
        <span key={index} className={cn("evidence-chip", `evidence-chip--${chip.tone}`)}>
          {chip.label}
        </span>
      ))}
    </div>
  );
}

/**
 * OctaInline — minimal, localized supervisor indicator shown inside the active
 * assistant response (so feedback stays visible when Octa near the composer is
 * scrolled out of view). Not a second status system: it renders the same live
 * supervisor label.
 */
function OctaInline({ state, label }: { state: OctaState; label: string }) {
  return (
    <span className="octa-inline" data-octa-state={state}>
      <Octa />
      <span className="octa-inline-label">{label}</span>
    </span>
  );
}

function ResearchTurnCard({ turn, liveState, liveLabel, busy = false, onClarify }: {
  turn: Turn;
  liveState?: OctaState;
  liveLabel?: string;
  busy?: boolean;
  onClarify?: (text: string) => void;
}) {
  const assistantResponse = getAssistantResponse(turn.response);
  const multiTask = assistantResponse && isMultiTaskResponse(assistantResponse) ? assistantResponse : null;
  const clarification = isClarificationData(assistantResponse?.metadata?.clarification)
    ? (assistantResponse!.metadata.clarification as ClarificationData)
    : null;
  // Presenter layer: map raw backend metadata into user-facing execution UX.
  const meta = (assistantResponse?.metadata ?? {}) as Record<string, any>;
  const phases = presentExecutionPhases(meta);
  // Runtime-action approval gets its own meaningful card (check descriptions,
  // commands tucked into a detail view) instead of generic buttons.
  const runtimeActions =
    meta.turn_status === "awaiting_action_approval" && Array.isArray(meta.runtime_actions)
      ? (meta.runtime_actions as Array<{ type?: string; description?: string; payload?: { command?: string } }>)
      : null;
  // A plan awaiting the user's go-ahead before real execution starts.
  const awaitingPlanApproval =
    !runtimeActions &&
    Boolean(meta.approval_required) &&
    Array.isArray(meta.plan_steps);
  const evidenceChips =
    meta.turn_status === "completed" || meta.turn_status === "failed"
      ? summarizeEvidence(meta)
      : [];
  const provenance = provenanceLabel(meta.answered_from, meta.evidence_strength);
  const artifact = presentArtifact(meta);
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
              AIRA-X
            </p>
          </div>
          <div className="aira-answer-body">
            {turn.streamingText ? (
              <AssistantAnswerContent answer={turn.streamingText} />
            ) : (
              <OctaInline state={liveState ?? "thinking"} label={liveLabel ?? "Thinking…"} />
            )}
            <span className="ml-0.5 inline-block animate-pulse text-[var(--accent)]">▌</span>
          </div>
          {turn.streamSources && turn.streamSources.length > 0 && (
            <div className="mt-4 aira-citations-block">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Sources</p>
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
              {provenance && (
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">{provenance}</p>
              )}
              {multiTask && taskCount > 0 && (
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                  {failedTasks.length > 0
                    ? `${completedTasks} completed · ${failedTasks.length} failed`
                    : `${taskCount} tasks completed`}
                </p>
              )}
            </div>
          </div>

          {/* Answer body — structured clarifications render as option cards
              instead of the markdown fallback text. */}
          <div className="aira-answer-body">
            {phases && <ExecutionProgress phases={phases} />}
            {clarification && onClarify ? (
              <ClarificationCard data={clarification} busy={busy} onSubmit={onClarify} />
            ) : (
              <AssistantAnswerContent answer={turn.response.answer} />
            )}
            {artifact && <ArtifactCard artifact={artifact} />}
            {evidenceChips.length > 0 && <EvidenceStrip chips={evidenceChips} />}
            {runtimeActions && onClarify && (
              <RuntimeApprovalCard actions={runtimeActions} busy={busy} onDecide={onClarify} />
            )}
            {awaitingPlanApproval && onClarify && (
              <PlanApprovalActions busy={busy} onDecide={onClarify} />
            )}
          </div>

          {/* Citations */}
          {turn.response.citations.length > 0 && (
            <div className="mt-4 aira-citations-block">
              <p className="mb-2.5 type-label text-[var(--text-subtle)]">Sources</p>
              <CitationList citations={turn.response.citations} />
            </div>
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
  question, setQuestion, busy, loading, octaState, octaMessage, octaProgress, octaInspector,
  onSubmit, onComposerFocus, attachedItems, onRemoveItem, onClearContext, onSaveBundle,
}: {
  question: string;
  setQuestion: (v: string) => void;
  busy: boolean;
  loading: boolean;
  octaState: OctaState;
  octaMessage?: string | null;
  octaProgress?: string | null;
  octaInspector?: OctaInspectorData;
  onSubmit: (e: FormEvent) => Promise<void>;
  onComposerFocus: () => void;
  attachedItems: AttachedContext[];
  onRemoveItem: (item: AttachedContext) => void;
  onClearContext: () => void;
  onSaveBundle: () => void;
}) {
  return (
    <section className="assistant-empty-shell w-full">
      <div className="w-full max-w-2xl text-center">
        {/* Animated logo */}
        <div className="flex justify-center mb-5">
          <AiraLogo size="lg" />
        </div>

        <p className="aira-kicker mb-3">AIRA-X Assistant</p>

        <h2 className="type-display text-[var(--text-strong)] md:text-[2.6rem] md:leading-[1.1]">
          How can I help<br />
          <span className="aira-gradient-text">you today?</span>
        </h2>

        <p className="mx-auto mt-3 max-w-lg type-body text-[var(--text-muted)]">
          Ask anything, analyze documents, plan projects, or run a workflow.
          Routing is handled automatically.
        </p>

        {/* Octa — companion above the composer */}
        <OctaStatus
          state={octaState}
          message={octaMessage ?? undefined}
          progress={octaProgress}
          inspector={octaInspector}
          size="lg"
          className="mt-8"
        />

        {/* Composer */}
        <form onSubmit={onSubmit} className="aira-home-composer mt-4 text-left">
          <ContextStack
            items={attachedItems}
            onRemoveItem={onRemoveItem}
            onClearAll={onClearContext}
            onSaveBundle={onSaveBundle}
          />
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
          <h2 className="type-heading text-[var(--text-strong)]">
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

      <CleanupActions memory={response.memory} />
    </div>
  );
}

// ─── Focus Composer Overlay ───────────────────────────────────────────────────

// ─── Uploaded document chips ──────────────────────────────────────────────────

function DocChips({ docs, onRemove }: { docs: string[]; onRemove?: (index: number) => void }) {
  if (docs.length === 0) return null;
  return (
    <div className="aira-doc-chips">
      {docs.map((name, index) => (
        <span key={`${name}-${index}`} className="aira-doc-chip" title={`${name} — uploaded`}>
          <FileText className="h-3 w-3 shrink-0" />
          <span className="aira-doc-chip-name">{name}</span>
          {onRemove && (
            <button
              type="button"
              className="aira-doc-chip-x"
              aria-label={`Dismiss ${name}`}
              onClick={() => onRemove(index)}
            >
              ×
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

// ─── Attached prior-work context (multi-item) ─────────────────────────────────

/** A calm, removable stack of pills showing the prior work attached to the next
 *  message — one per item, with a header summary, clear-all, and save-as-bundle.
 *  Never hidden, never a blob; the user's typed message still leads. */
function ContextStack({
  items, onRemoveItem, onClearAll, onSaveBundle,
}: {
  items: AttachedContext[];
  onRemoveItem: (item: AttachedContext) => void;
  onClearAll: () => void;
  onSaveBundle: () => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mb-2 flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 px-0.5">
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[var(--accent)]">
          <Sparkles className="h-3 w-3 shrink-0" />
          {itemsSummary(items)}
        </span>
        <span className="flex items-center gap-2 text-xs">
          <button type="button" onClick={onSaveBundle} className="font-semibold text-[var(--text-muted)] hover:text-[var(--accent)]">
            Save as bundle
          </button>
          <button type="button" onClick={onClearAll} className="font-semibold text-[var(--text-muted)] hover:text-[var(--warning)]">
            Clear all
          </button>
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={`${item.ref_type}-${item.ref_id}`}
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-1 text-xs font-bold text-[var(--accent)]"
            title={item.summary}
          >
            <span className="truncate">{contextLabel(item)}</span>
            <button
              type="button"
              aria-label={`Remove ${item.title}`}
              className="ml-0.5 shrink-0 rounded-full px-1 text-sm leading-none hover:opacity-70"
              onClick={() => onRemoveItem(item)}
            >
              ×
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Attach (upload) button ───────────────────────────────────────────────────

function AttachButton({ onClick, uploading, disabled }: {
  onClick: () => void;
  uploading: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={uploading || disabled}
      className="aira-attach-btn"
      aria-label="Attach a document"
      title="Attach a PDF, DOCX, TXT, or Markdown file"
    >
      {uploading ? <span className="aira-send-spinner" /> : <Paperclip className="h-4 w-4" />}
    </button>
  );
}

function FocusComposerOverlay({
  question, setQuestion, busy, loading, airaXLoading, onSubmit, onClose,
  onAttach, uploading, uploadedDocs, onRemoveDoc,
}: {
  question: string;
  setQuestion: (v: string) => void;
  busy: boolean;
  loading: boolean;
  airaXLoading: boolean;
  onSubmit: (e: FormEvent) => Promise<void>;
  onClose: () => void;
  onAttach: () => void;
  uploading: boolean;
  uploadedDocs: string[];
  onRemoveDoc: (index: number) => void;
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

        <DocChips docs={uploadedDocs} onRemove={onRemoveDoc} />

        <textarea
          autoFocus
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Message AIRA-X…"
          className="aira-focus-textarea"
        />

        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <AttachButton onClick={onAttach} uploading={uploading} disabled={busy && !uploading} />
            <p className="hidden text-xs text-[var(--text-subtle)] sm:block">
              <kbd className="aira-kbd">Esc</kbd> to exit focus mode
            </p>
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

/* ── Octa — supervisor mascot (companion above the composer) ── */
.octa-companion {
  display: flex;
  gap: 0.55rem;
  --octa-eye: #3fa9ff;
  --octa-glow: rgba(110, 193, 255, 0.55);
  --octa-accent: #6ec1ff;
}
.octa-companion--lg { flex-direction: column; align-items: center; text-align: center; }
.octa-companion--sm { flex-direction: row; align-items: center; }
html[data-scheme="dark"] .octa-companion {
  --octa-eye: #00d4ff;
  --octa-glow: rgba(0, 212, 255, 0.7);
}

.octa-figure {
  position: relative;
  line-height: 0;
  display: inline-flex;
  padding: 0;
  border: 0;
  background: none;
  cursor: pointer;
  border-radius: 14px;
  -webkit-tap-highlight-color: transparent;
  animation: octa-float 4s ease-in-out infinite;
  transition: filter 0.2s ease;
}
.octa-figure:hover { filter: drop-shadow(0 0 9px var(--octa-glow)); }
.octa-figure:active { filter: drop-shadow(0 0 12px var(--octa-glow)); }
.octa-figure:focus-visible { outline: 2px solid var(--octa-accent); outline-offset: 4px; }
/* subtle click squish */
.octa-figure--poke { animation: octa-poke 0.5s ease; }
@keyframes octa-poke {
  0%   { transform: translateY(0) scale(1, 1); }
  30%  { transform: translateY(1px) scale(1.08, 0.92); }
  60%  { transform: translateY(-3px) scale(0.97, 1.04); }
  100% { transform: translateY(0) scale(1, 1); }
}

/* ink puff — a soft cyan cloud that blooms around Octa and fades */
.octa-ink {
  position: absolute;
  left: 50%;
  top: 58%;
  width: 140%;
  height: 140%;
  transform: translate(-50%, -50%) scale(0.4);
  border-radius: 50%;
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--octa-accent) 85%, transparent) 0%,
    color-mix(in srgb, var(--octa-accent) 45%, transparent) 40%,
    transparent 70%
  );
  filter: blur(1px);
  opacity: 0;
  pointer-events: none;
  z-index: 0;
  animation: octa-ink 0.75s ease-out forwards;
}
@keyframes octa-ink {
  0%   { opacity: 0.75; transform: translate(-50%, -50%) scale(0.4); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.9); }
}

/* idle micro-moments (random, idle only) */
.octa-svg[data-micro="blink"] .o-blink { animation: octa-microblink 0.5s ease; }
.octa-svg[data-micro="curl"] .o-arm-3 { animation: octa-microcurl 1.1s ease; }
.octa-svg[data-micro="look"] .o-eyes { transform-box: fill-box; transform-origin: center; animation: octa-microlook 1.3s ease-in-out; }
@keyframes octa-microblink { 0%, 100% { transform: scaleY(1); } 45% { transform: scaleY(0.12); } }
@keyframes octa-microcurl {
  0%, 100% { transform: translateY(0) scaleY(1); }
  45%      { transform: translateY(-1px) scaleY(0.72); }
}
@keyframes octa-microlook {
  0%, 100% { transform: translateX(0); }
  30%      { transform: translateX(-1.2px); }
  65%      { transform: translateX(1.2px); }
}
.octa-svg { position: relative; z-index: 1; display: block; overflow: visible; image-rendering: pixelated; animation: octa-breathe 5s ease-in-out infinite; }
.octa-companion--lg .octa-svg { width: 72px; height: 72px; }
.octa-companion--sm .octa-svg { width: 40px; height: 40px; }

/* Octa palette (brand) */
.octa-svg .o-head { fill: #6ec1ff; }
.octa-svg .o-head-hi { fill: #aee4ff; }
.octa-svg .o-head-lo { fill: #4fa3ec; }
.octa-svg .o-arm { fill: #5bb0f0; }
.octa-svg .o-arm-lo { fill: #3f93d8; }
.octa-svg .o-visor { fill: #14233b; }
.octa-svg .o-accent { fill: #aee4ff; }
.octa-svg .o-eye { fill: var(--octa-eye); filter: drop-shadow(0 0 1.5px var(--octa-glow)); }
.octa-svg .o-scan { fill: var(--octa-eye); opacity: 0; }
html[data-scheme="light"] .octa-svg .o-visor { fill: #1c2d49; }

/* idle motion: gentle blink, antenna pulse, slow tentacle wave */
.octa-svg .o-blink { transform-box: fill-box; transform-origin: center; animation: octa-blink 5s infinite; }
.octa-svg .o-pulse { animation: octa-glow 3.4s ease-in-out infinite; }
.octa-svg .o-arm-grp { transform-box: fill-box; transform-origin: center top; animation: octa-wave 4s ease-in-out infinite; }
.octa-svg .o-arm-2 { animation-delay: 0.3s; }
.octa-svg .o-arm-3 { animation-delay: 0.6s; }
.octa-svg .o-arm-4 { animation-delay: 0.9s; }
.octa-svg .o-arm-5 { animation-delay: 1.2s; }

@keyframes octa-float { 0%, 100% { transform: translateY(-2px); } 50% { transform: translateY(2px); } }
@keyframes octa-breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.02); } }
@keyframes octa-blink { 0%, 94%, 100% { transform: scaleY(1); } 97% { transform: scaleY(0.15); } }
@keyframes octa-glow { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
@keyframes octa-wave { 0%, 100% { transform: rotate(-3deg); } 50% { transform: rotate(3deg); } }
@keyframes octa-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.045); } }
@keyframes octa-scan { 0% { transform: translateX(0); } 100% { transform: translateX(18px); } }

/* per-state accent (subtle — drives bubble + a light eye/glow tint) */
.octa-companion[data-octa-state="routing"]     { --octa-accent: #7cc4ff; }
.octa-companion[data-octa-state="thinking"]    { --octa-accent: #6ec1ff; }
.octa-companion[data-octa-state="researching"] { --octa-accent: #00d4ff; --octa-eye: #00d4ff; --octa-glow: rgba(0, 212, 255, 0.6); }
.octa-companion[data-octa-state="reading"]     { --octa-accent: #a78bfa; --octa-eye: #a78bfa; --octa-glow: rgba(167, 139, 250, 0.55); }
.octa-companion[data-octa-state="memory"]      { --octa-accent: #3fd0c8; --octa-eye: #3fd0c8; --octa-glow: rgba(63, 208, 200, 0.55); }
.octa-companion[data-octa-state="executing"]   { --octa-accent: #f5963f; --octa-eye: #f5963f; --octa-glow: rgba(245, 150, 63, 0.55); }
.octa-companion[data-octa-state="approval"]    { --octa-accent: #f4c04a; --octa-eye: #f4c04a; --octa-glow: rgba(244, 192, 74, 0.5); }
.octa-companion[data-octa-state="clarify"]     { --octa-accent: #6ec1ff; --octa-eye: #8fd0ff; --octa-glow: rgba(110, 193, 255, 0.5); }
.octa-companion[data-octa-state="success"]     { --octa-accent: #3fe0a4; --octa-eye: #3fe0a4; --octa-glow: rgba(63, 224, 164, 0.6); }
.octa-companion[data-octa-state="error"]       { --octa-accent: #f26d6d; --octa-eye: #f26d6d; --octa-glow: rgba(242, 109, 109, 0.5); }

/* working states: subtle pulse + faster blink + scan line */
.octa-companion[data-octa-state="routing"] .octa-svg,
.octa-companion[data-octa-state="thinking"] .octa-svg,
.octa-companion[data-octa-state="researching"] .octa-svg,
.octa-companion[data-octa-state="reading"] .octa-svg,
.octa-companion[data-octa-state="memory"] .octa-svg,
.octa-companion[data-octa-state="executing"] .octa-svg { animation: octa-pulse 3s ease-in-out infinite; }
.octa-companion[data-octa-state="routing"] .o-blink,
.octa-companion[data-octa-state="thinking"] .o-blink,
.octa-companion[data-octa-state="researching"] .o-blink,
.octa-companion[data-octa-state="reading"] .o-blink,
.octa-companion[data-octa-state="memory"] .o-blink { animation-duration: 2.4s; }
.octa-companion[data-octa-state="routing"] .o-scan,
.octa-companion[data-octa-state="thinking"] .o-scan,
.octa-companion[data-octa-state="researching"] .o-scan,
.octa-companion[data-octa-state="reading"] .o-scan,
.octa-companion[data-octa-state="memory"] .o-scan,
.octa-companion[data-octa-state="executing"] .o-scan {
  transform-box: fill-box;
  opacity: 0.95;
  animation: octa-scan 1.1s ease-in-out infinite alternate;
}
.octa-companion[data-octa-state="researching"] .o-scan { animation-duration: 0.75s; }

/* executing: energetic tentacles + glow */
.octa-companion[data-octa-state="executing"] .octa-svg { filter: drop-shadow(0 0 6px var(--octa-glow)); }
.octa-companion[data-octa-state="executing"] .o-arm-grp { animation-duration: 1.5s; }

/* approval / clarify: calm, paused tentacles — waiting on the user */
.octa-companion[data-octa-state="approval"] .o-arm-grp,
.octa-companion[data-octa-state="clarify"] .o-arm-grp { animation: none; }
.octa-companion[data-octa-state="approval"] .o-blink,
.octa-companion[data-octa-state="clarify"] .o-blink { animation: octa-blink 2.8s infinite; }

/* success: soft glow */
.octa-companion[data-octa-state="success"] .octa-svg { filter: drop-shadow(0 0 7px var(--octa-glow)); }

/* error: dim, not alarming */
.octa-companion[data-octa-state="error"] .o-arm-grp { animation: none; }

/* status bubble — connected to Octa, accent per state */
.octa-bubble {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border: 1px solid color-mix(in srgb, var(--octa-accent) 40%, var(--border));
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 0.32rem 0.74rem;
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--text-strong);
  max-width: min(78vw, 22rem);
  box-shadow: var(--shadow-card), 0 0 0 3px color-mix(in srgb, var(--octa-accent) 8%, transparent);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
  /* entrance pulse — replays on each state change (bubble is keyed by state) */
  animation: octa-bubble-pop 0.55s ease;
}
/* expanding accent ring on state entrance */
.octa-bubble::after {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: 999px;
  border: 1px solid var(--octa-accent);
  opacity: 0;
  pointer-events: none;
  animation: octa-bubble-ring 0.6s ease-out;
}
@keyframes octa-bubble-pop {
  0%   { transform: scale(0.95); }
  55%  { transform: scale(1.035); }
  100% { transform: scale(1); }
}
@keyframes octa-bubble-ring {
  0%   { opacity: 0.5; transform: scale(0.96); }
  100% { opacity: 0; transform: scale(1.14); }
}
.octa-bubble-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  flex-shrink: 0;
  background: var(--octa-accent);
  box-shadow: 0 0 6px var(--octa-accent);
  animation: octa-glow 1.6s ease-in-out infinite;
}
.octa-bubble-icon { width: 0.85rem; height: 0.85rem; flex-shrink: 0; color: var(--octa-accent); }
.octa-bubble-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* idle is calm — mute the accent */
.octa-companion[data-octa-state="idle"] .octa-bubble { color: var(--text-muted); }
.octa-companion[data-octa-state="idle"] .octa-bubble-dot { animation: none; box-shadow: none; opacity: 0.65; }

/* figure wrapper anchors the route badge + inspector popover */
.octa-figure-wrap { position: relative; display: inline-flex; }
.octa-bubble-row { display: inline-flex; align-items: center; gap: 0.35rem; min-width: 0; }
.octa-bubble-progress { font-weight: 600; color: var(--text-muted); }

/* route badge — tiny glyph showing the active supervisor path */
.octa-route-badge {
  position: absolute;
  right: -4px;
  top: -2px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--octa-accent) 55%, var(--border));
  background: var(--surface);
  color: var(--octa-accent);
  box-shadow: 0 0 5px color-mix(in srgb, var(--octa-accent) 35%, transparent);
  pointer-events: none;
}
.octa-route-badge-icon { width: 9px; height: 9px; }

/* supervisor inspector — read-only system facts, console-like */
.octa-inspector {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 60;
  width: min(210px, 86vw);
  border: 1px solid var(--border-strong);
  border-radius: 0.8rem;
  background: var(--surface);
  box-shadow: var(--shadow-card), 0 12px 40px rgba(0, 0, 0, 0.35);
  padding: 0.45rem 0.6rem 0.5rem;
  text-align: left;
  cursor: default;
}
.octa-inspector-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.66rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-subtle);
  margin-bottom: 0.3rem;
}
.octa-inspector-close {
  display: inline-flex;
  padding: 2px;
  border-radius: 6px;
  color: var(--text-subtle);
}
.octa-inspector-close:hover { color: var(--text-strong); }
.octa-inspector-status {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  margin: 0 0 0.4rem;
  font-size: 0.82rem;
  font-weight: 800;
  color: var(--text-strong);
}
.octa-inspector-status-dot {
  width: 0.5rem;
  height: 0.5rem;
  flex-shrink: 0;
  border-radius: 999px;
  background: var(--octa-accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--octa-accent) 60%, transparent);
}
.octa-inspector-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.14rem 0.65rem;
  margin: 0;
}
.octa-inspector-grid dt {
  font-size: 0.64rem;
  font-weight: 600;
  color: var(--text-subtle);
}
.octa-inspector-grid dd {
  margin: 0;
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* info button — small, attached to the bubble */
.octa-info-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.05rem;
  height: 1.05rem;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  font-size: 0.62rem;
  font-weight: 800;
  font-style: italic;
  color: var(--text-subtle);
  cursor: pointer;
}
.octa-info-btn:hover { color: var(--text-strong); border-color: var(--border-strong); }
.octa-info-btn:focus-visible { outline: 2px solid var(--octa-accent); outline-offset: 2px; }

/* ── Clarification option cards ── */
.clarify-card { display: flex; flex-direction: column; gap: 1rem; }
.clarify-intro {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-strong);
}
.clarify-section { display: flex; flex-direction: column; gap: 0.5rem; }
.clarify-section-title {
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-subtle);
}
.clarify-options { display: flex; flex-direction: column; gap: 0.4rem; }
.clarify-option {
  width: 100%;
  text-align: left;
  border: 1px solid var(--border);
  border-radius: 0.8rem;
  background: var(--surface-soft);
  padding: 0.6rem 0.9rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.clarify-option:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--surface-hover);
  color: var(--text-strong);
}
.clarify-option--selected,
.clarify-option--selected:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 60%, transparent);
  background: var(--accent-soft);
  color: var(--text-strong);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent);
}
.clarify-option:disabled { opacity: 0.55; cursor: not-allowed; }
.clarify-custom-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 0.7rem;
  background: var(--surface-strong);
  padding: 0.55rem 0.8rem;
  font-size: 0.82rem;
  color: var(--text-strong);
  outline: none;
}
.clarify-custom-input:focus {
  border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 10%, transparent);
}
.clarify-continue {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border-radius: 0.85rem;
  background: var(--accent);
  color: var(--accent-foreground);
  padding: 0.6rem 1.1rem;
  font-size: 0.8rem;
  font-weight: 800;
  cursor: pointer;
  box-shadow: var(--shadow-soft);
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.clarify-continue:hover:not(:disabled) { transform: translateY(-1px); }
.clarify-continue:disabled { opacity: 0.5; cursor: not-allowed; }

/* plan approval actions */
.plan-approval-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }
.plan-reject-btn {
  display: inline-flex;
  align-items: center;
  border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
  border-radius: 0.85rem;
  background: var(--danger-soft);
  color: var(--danger);
  padding: 0.6rem 1.1rem;
  font-size: 0.8rem;
  font-weight: 800;
  cursor: pointer;
}
.plan-reject-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Premium execution UX ── */
.exec-progress {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
  margin-bottom: 1rem;
  padding: 0.55rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 0.9rem;
  background: var(--surface-soft);
}
.exec-phase {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-subtle);
}
.exec-phase-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: var(--border-strong);
  flex-shrink: 0;
}
.exec-phase--done { color: var(--text-muted); }
.exec-phase--done .exec-phase-dot { background: var(--success, #15a06a); }
.exec-phase--active { color: var(--text-strong); }
.exec-phase--active .exec-phase-dot {
  background: var(--accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 60%, transparent);
  animation: octa-glow 1.6s ease-in-out infinite;
}
.exec-phase--failed { color: var(--danger); }
.exec-phase--failed .exec-phase-dot { background: var(--danger); }

.runtime-approval-card {
  margin-top: 1rem;
  border: 1px solid color-mix(in srgb, var(--warning, #d9822b) 35%, var(--border));
  border-radius: 1rem;
  background: var(--surface-soft);
  padding: 0.9rem 1rem;
}
.runtime-approval-title { font-size: 0.875rem; font-weight: 800; color: var(--text-strong); }
.runtime-approval-sub { margin-top: 0.3rem; font-size: 0.78rem; line-height: 1.5; color: var(--text-muted); }
.runtime-approval-list { margin: 0.6rem 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 0.3rem; }
.runtime-approval-list li {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.runtime-approval-list li::before {
  content: "";
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 999px;
  background: var(--accent);
  flex-shrink: 0;
}
.runtime-approval-details { margin-top: 0.6rem; }
.runtime-approval-details summary {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-subtle);
  cursor: pointer;
}
.runtime-approval-details pre {
  margin-top: 0.4rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: 0.6rem;
  background: var(--surface-muted);
  font-size: 0.7rem;
  line-height: 1.5;
  overflow-x: auto;
  color: var(--text-muted);
}

.evidence-strip { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.9rem; }
.evidence-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.22rem 0.65rem;
  font-size: 0.7rem;
  font-weight: 700;
  border: 1px solid var(--border);
  background: var(--surface-soft);
  color: var(--text-muted);
}
.evidence-chip--good {
  color: var(--success, #15a06a);
  border-color: color-mix(in srgb, var(--success, #15a06a) 40%, transparent);
  background: var(--success-soft, var(--surface-soft));
}
.evidence-chip--warn {
  color: var(--warning, #d9822b);
  border-color: color-mix(in srgb, var(--warning, #d9822b) 40%, transparent);
}
.evidence-chip--bad {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 40%, transparent);
}

/* artifact result card */
.artifact-card {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin-top: 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
  border-radius: 1rem;
  background: var(--surface-soft);
}
.artifact-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.4rem;
  height: 2.4rem;
  flex-shrink: 0;
  border-radius: 0.7rem;
  background: var(--accent-soft);
  color: var(--accent);
}
.artifact-body { min-width: 0; flex: 1; }
.artifact-title {
  font-size: 0.9rem;
  font-weight: 800;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-subtitle { margin-top: 0.1rem; font-size: 0.76rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artifact-meta { margin-top: 0.2rem; font-size: 0.74rem; font-weight: 600; color: var(--text-muted); }
.artifact-valid { color: var(--success, #15a06a); }
.artifact-loc { margin-top: 0.15rem; font-size: 0.68rem; color: var(--text-subtle); }
.artifact-note { margin-top: 0.3rem; font-size: 0.72rem; color: var(--text-subtle); }
.artifact-download {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  border-radius: 0.7rem;
  background: var(--accent);
  color: var(--accent-foreground);
  padding: 0.5rem 0.95rem;
  font-size: 0.78rem;
  font-weight: 800;
  text-decoration: none;
}
.artifact-download:hover { transform: translateY(-1px); }

/* localized in-message indicator (inside the streaming answer card) */
.octa-inline {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  --octa-eye: #3fa9ff;
  --octa-glow: rgba(110, 193, 255, 0.55);
  --octa-accent: #6ec1ff;
}
html[data-scheme="dark"] .octa-inline { --octa-eye: #00d4ff; --octa-glow: rgba(0, 212, 255, 0.7); }
.octa-inline .octa-svg { width: 18px; height: 18px; animation: octa-breathe 5s ease-in-out infinite; }
.octa-inline-label { font-size: 0.8rem; color: var(--text-muted); }

@media (max-width: 640px) {
  .octa-companion--sm { gap: 0.4rem; }
  .octa-companion--sm .octa-svg { width: 38px; height: 38px; }
  .octa-bubble { max-width: 62vw; }
  .octa-bubble-label { white-space: normal; }
}
@media (prefers-reduced-motion: reduce) {
  .octa-figure, .octa-svg, .octa-svg *, .octa-bubble-dot,
  .octa-ink, .octa-bubble, .octa-bubble::after { animation: none !important; }
  .octa-ink, .octa-bubble::after { display: none; }
}

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
html[data-scheme="dark"] .aira-card::before {
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
html[data-scheme="dark"] .aira-answer-card {
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

/* ── Attach (upload) button ── */
.aira-attach-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  height: 2.25rem;
  width: 2.25rem;
  border-radius: 0.75rem;
  border: 1px solid var(--border);
  background: var(--surface-muted);
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.aira-attach-btn:hover:not(:disabled) {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.aira-attach-btn:disabled { cursor: not-allowed; opacity: 0.5; }
.aira-attach-btn .aira-send-spinner {
  border: 2px solid color-mix(in srgb, var(--text-muted) 30%, transparent);
  border-top-color: var(--accent);
}

/* ── Uploaded document chips ── */
.aira-doc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.6rem;
}
.aira-doc-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  max-width: 240px;
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
  background: var(--accent-soft);
  color: var(--text-strong);
  font-size: 0.72rem;
  font-weight: 600;
}
.aira-doc-chip-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aira-doc-chip-x {
  display: inline-flex;
  align-items: center;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.95rem;
  line-height: 1;
  padding: 0 0 0 0.1rem;
}
.aira-doc-chip-x:hover { color: var(--danger); }

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
  // Stable, persisted across reloads and shared with the Settings page, so the
  // preferences a user edits in Settings apply to this session's answers.
  const [sessionId] = useState(getSessionId);
  const [uploadedDocs, setUploadedDocs] = useState<string[]>([]);
  // Persistent "documents are available this conversation" signal — kept even if
  // the user dismisses a chip, so document-first routing keeps working.
  const [sessionDocNames, setSessionDocNames] = useState<string[]>([]);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const threadBottomRef = useRef<HTMLDivElement>(null);

  // Octa companion state — mirrors the live supervisor state.
  const [octaState, setOctaState] = useState<OctaState>("idle");
  // Live execution phase for the active streaming turn (planning → executing →
  // validating → starting app → readiness → repairing …). Driven only by real
  // SSE `stage`/`classified` events; cleared when the turn resolves so no stale
  // progress lingers. Raw backend names never reach this — see live-phase-presenter.
  const [livePhase, setLivePhase] = useState<LivePhase | null>(null);
  // Transient, event-driven supervisor message (e.g. "Document indexed…").
  const [octaFlash, setOctaFlash] = useState<string | null>(null);
  const octaFlashRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // NOTE: success/error deliberately persist until the next message is sent —
  // terminal supervisor state should not auto-dismiss.

  // Trace awareness — real values from supervisor events, shown in the inspector.
  const [lastRoute, setLastRoute] = useState<string | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  const turnStartRef = useRef<number | null>(null);

  // Flash a brief Supervisor event message through Octa, then clear it.
  const flashOcta = (msg: string) => {
    setOctaFlash(msg);
    if (octaFlashRef.current) clearTimeout(octaFlashRef.current);
    octaFlashRef.current = setTimeout(() => setOctaFlash(null), 3600);
  };

  const busy = loading || airaXLoading || approvalLoading || rejectionLoading || uploadLoading;
  const threadIsEmpty = useMemo(() => turns.length === 0 && !airaXResponse, [turns.length, airaXResponse]);

  // Workflow/research progress — only from real backend data, never simulated.
  const octaProgress = useMemo(() => {
    if (octaState === "researching") {
      const live = turns.find((t) => t.streaming)?.streamSources?.length ?? 0;
      return live > 0 ? `(${live} source${live === 1 ? "" : "s"} found)` : null;
    }
    if ((octaState === "executing" || octaState === "approval") && airaXResponse) {
      const step = airaXResponse.current_step;
      const total = airaXResponse.plan?.length ?? 0;
      if (typeof step === "number" && step > 0 && total > 0) {
        return `(step ${Math.min(step, total)} of ${total})`;
      }
    }
    return null;
  }, [octaState, turns, airaXResponse]);

  // Session awareness: before the first turn the supervisor reports a fresh
  // session; afterwards plain "Ready". Event flashes take precedence, then the
  // live execution phase (so the composer Octa narrates real progress).
  const liveMessage = livePhase && livePhase.tone === "active" ? livePhase.label : undefined;
  const octaMessage =
    octaFlash ?? liveMessage ?? (octaState === "idle" && turns.length === 0 ? "New session" : undefined) ?? undefined;

  const octaInspector: OctaInspectorData = {
    lastRoute,
    runId: lastRunId,
    documentsIndexed: sessionDocNames.length,
    memoryActive: turns.length > 0,
    sessionId,
    lastLatencyMs,
  };

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

  // "Continue your work" handoff: a run picked from Settings leaves a prepared
  // prompt here. Prefill the composer (never auto-send) so the user stays in
  // control and the continuation runs as a normal scoped turn — chat-native.
  useEffect(() => {
    const prompt = takeContinuation();
    if (prompt) {
      setQuestion(prompt);
      flashOcta("Continuing where you left off");
    }
  }, []);

  // Chat-native context handoff: documents/artifacts/runs "used in chat" from
  // scope-aware surfaces (or a loaded bundle) are parked server-side on this
  // session. Surface them as calm, removable pills and prefill an honest starter
  // — never hidden context, always explicit and editable.
  const [attachedItems, setAttachedItems] = useState<AttachedContext[]>([]);
  useEffect(() => {
    fetchContext(sessionId)
      .then((state) => {
        if (state.items.length > 0) {
          setAttachedItems(state.items);
          if (state.prompt) setQuestion(state.prompt);
          flashOcta(itemsSummary(state.items));
        }
      })
      .catch(() => {});
  }, [sessionId]);

  const onRemoveItem = useCallback((item: AttachedContext) => {
    setAttachedItems((prev) => prev.filter((i) => !(i.ref_type === item.ref_type && i.ref_id === item.ref_id)));
    void removeContextItem(item.ref_type, item.ref_id, sessionId);
  }, [sessionId]);

  const onClearContext = useCallback(() => {
    setAttachedItems([]);
    void clearContext(sessionId);
  }, [sessionId]);

  const onSaveBundle = useCallback(async () => {
    const name = typeof window !== "undefined" ? window.prompt("Name this handoff pack")?.trim() : "";
    if (!name) return;
    const bundle = await createBundle(name, sessionId);
    flashOcta(bundle ? `Saved bundle “${bundle.name}”` : "Couldn't save bundle");
  }, [sessionId]);

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

  async function handleUnifiedAssistant(event?: FormEvent, overrideText?: string) {
    event?.preventDefault();
    // `overrideText` lets UI elements (e.g. clarification option cards) submit
    // a message programmatically without touching the composer draft.
    const trimmed = (overrideText ?? question).trim();
    if (!trimmed) return;

    setComposerFocused(false);
    if (!overrideText) setQuestion("");
    // Attached context is single-use for this message (the server consumes it),
    // so the pills clear as the turn is sent — never lingering, never hidden.
    setAttachedItems([]);
    setLoading(true);
    setAiraXLoading(false);
    setOctaFlash(null);
    setLivePhase(null);
    setOctaState("routing");
    turnStartRef.current = Date.now();

    // Build recent conversation history (last few turns) so follow-ups have context.
    const history = turns
      .flatMap((t) => {
        const msgs: { role: "user" | "assistant"; content: string }[] = [
          { role: "user", content: t.question },
        ];
        const answer = getAssistantResponse(t.response)?.answer ?? t.streamingText;
        if (answer && answer.trim()) msgs.push({ role: "assistant", content: answer });
        return msgs;
      })
      .slice(-8);

    const turnId =
      typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    setTurns((prev) => [...prev, { id: turnId, question: trimmed, streaming: true, streamingText: "" }]);

    let finalData: Record<string, unknown> | null = null;

    try {
      await streamAiraX(
        trimmed,
        {
          onTrace: (data) => {
            // The "classified" trace tells us which capability is running.
            if (data?.event === "classified" && typeof data.mode === "string") {
              setOctaState(octaStateForMode(data.mode));
              setLastRoute(data.mode);
              setLivePhase((prev) => livePhaseForMode(data.mode as string) ?? prev);
            }
            // Live phase progression: each `stage` event advances the active
            // turn's phase. Unknown stages keep the current phase (no raw enums).
            if (data?.event === "stage" && typeof data.stage === "string") {
              setLivePhase((prev) => livePhaseForStage(data.stage as string) ?? prev);
            }
          },
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
          onFinal: (data) => {
            finalData = data;
          },
          onError: (message) => {
            throw new Error(message);
          },
        },
        { sessionId, history, uploadedFileNames: sessionDocNames }
      );

      if (!finalData) {
        throw new Error("Stream ended without a final response.");
      }

      const final = finalData as AssistantRunResponse & Record<string, unknown>;
      const mode = String((final as Record<string, unknown>).mode ?? "");

      // Only a real run (or a workflow-level approval gate) renders as a workflow
      // card. Plan/clarification/artifact turns awaiting approval stay in the
      // answer card, which carries their Approve/Reject controls.
      const isWorkflow = isWorkflowResult(final as FinalLike);

      if (isWorkflow) {
        const run = assistantWorkflowToAiraXRun(final as unknown as Parameters<typeof assistantWorkflowToAiraXRun>[0]);
        if (run) {
          setAiraXResponse(run);
          setLastRunId(run.run_id ?? null);
          if (turnStartRef.current) setLastLatencyMs(Date.now() - turnStartRef.current);
          if (run.requires_approval) {
            setOctaState("approval");
          } else {
            setOctaState(run.status === "completed" || run.success ? "success" : "error");
          }
          removeTurnById(turnId);
          return;
        }
      }

      // Chat / web research / self-memory: finalize the streamed bubble. Keep
      // the text already streamed token-by-token; the final event only marks
      // completion and attaches sources/metadata (it must not re-render the
      // whole answer or duplicate it).
      const finalAnswer = String(
        final.message ?? (final as Record<string, unknown>).final_answer ?? ""
      );
      const citations = Array.isArray(final.sources) ? (final.sources as Citation[]) : [];
      const runId = typeof final.run_id === "string" ? final.run_id : null;
      const rawMeta = ((final as Record<string, unknown>).meta as Record<string, unknown>) ?? {};
      // Carry status/decision into the turn so the presenter layer can map
      // execution phases without re-parsing the stream.
      const meta = {
        ...rawMeta,
        turn_status: String((final as Record<string, unknown>).status ?? ""),
        turn_decision: String((final as Record<string, unknown>).decision ?? ""),
      };
      setAiraXResponse(null);
      setTurns((prev) =>
        prev.map((t) => {
          if (t.id !== turnId) return t;
          const streamed = (t.streamingText || "").trim();
          return {
            ...t,
            streaming: false,
            response: {
              response_type: modeToResponseType(mode),
              answer: streamed || finalAnswer,
              citations,
              workflow: null,
              run_id: runId,
              metadata: meta,
            },
          };
        })
      );
      // Waiting states are not completed tasks: a clarification reply waits on
      // details, and a ready plan waits on approval before anything executes.
      const finalStatus = String((final as Record<string, unknown>).status ?? "");
      if (mode === "clarification") {
        setOctaState("clarify");
      } else if (finalStatus === "plan_ready") {
        setOctaState("approval");
        flashOcta("Plan ready — approval required.");
      } else if (finalStatus === "awaiting_action_approval") {
        setOctaState("approval");
        flashOcta("Files written — approve runtime validation.");
      } else {
        setOctaState("success");
      }
      setLastRunId(runId);
      if (turnStartRef.current) setLastLatencyMs(Date.now() - turnStartRef.current);
      // Context-aware: surface a source count for research turns.
      if (mode === "web_research" && citations.length > 0) {
        flashOcta(`Found ${citations.length} relevant source${citations.length === 1 ? "" : "s"}.`);
      }
    } catch (streamError) {
      // Graceful fallback to the non-streaming endpoint.
      try {
        const response = await runAssistant(trimmed, true);
        applyNonStreamingResponse(turnId, trimmed, response);
        setOctaState("success");
      } catch (fallbackError) {
        const message =
          fallbackError instanceof Error ? fallbackError.message : "AIRA-X assistant failed.";
        patchTurnById(turnId, { streaming: false, streamingText: undefined, error: message });
        setOctaState("error");
      }
    } finally {
      setLoading(false);
      setAiraXLoading(false);
      // The turn has resolved (success, approval-gate, or error) — drop the live
      // phase so no stale progress indicator lingers on the next render.
      setLivePhase(null);
    }
  }

  async function handleApproveAiraX() {
    if (!airaXResponse?.run_id) return;
    setApprovalLoading(true);
    setOctaState("executing");
    try {
      const result = await approveAiraX(airaXResponse.run_id);
      setAiraXResponse(result);
      if (result.requires_approval) {
        setOctaState("approval");
      } else {
        setOctaState(result.status === "completed" || result.success ? "success" : "error");
      }
    } catch (error) {
      console.error("AIRA-X Approval Error:", error);
      setOctaState("error");
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
      setOctaState("idle");
    } catch (error) {
      console.error("AIRA-X Rejection Error:", error);
      setOctaState("error");
    } finally {
      setRejectionLoading(false);
    }
  }

  async function handleUploadDocuments(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    const names = Array.from(files).map((f) => f.name);
    setUploadLoading(true);
    setUploadMessage("");
    setUploadError("");
    try {
      const result = await uploadDocuments(files, sessionId);
      const count = result.documents?.length || files.length;
      const firstEver = sessionDocNames.length === 0;
      setUploadedDocs((prev) => [...prev, ...names]);
      // Persisted for the whole conversation so document Q&A keeps working even
      // after the visual chip is dismissed.
      setSessionDocNames((prev) => Array.from(new Set([...prev, ...names])));
      setUploadMessage(
        `${count} document${count === 1 ? "" : "s"} uploaded and indexed. You can now ask about ${count === 1 ? "it" : "them"}.`
      );
      // Context-aware Octa signal from a real supervisor event.
      flashOcta(firstEver ? "Document Q&A is now available." : "Document indexed successfully.");
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Document upload failed.");
    } finally {
      setUploadLoading(false);
      event.target.value = "";
    }
  }

  function removeUploadedDocChip(index: number) {
    // Dismisses the visual chip only. The document stays ingested AND remains in
    // sessionDocNames, so document Q&A keeps working for the rest of the chat.
    setUploadedDocs((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(event: FormEvent) {
    await handleUnifiedAssistant(event);
  }

  return (
    <>
      <AiraStyles />

      <div className={cn(
        "mx-auto flex h-full min-h-0 w-full flex-col gap-4 px-4 py-4",
        threadIsEmpty ? "max-w-2xl" : "max-w-3xl",
        "aira-chat-page"
      )}>
        <input
          ref={uploadInputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.txt,.md,.markdown"
          className="hidden"
          onChange={handleUploadDocuments}
        />

        {/* Upload feedback */}
        {(uploadMessage || uploadError) && (
          <div className={cn(
            "rounded-xl border px-4 py-2.5 type-body-strong",
            uploadError
              ? "border-[color-mix(in_srgb,var(--danger)_30%,transparent)] bg-[var(--danger-soft)] text-[var(--danger)]"
              : "border-[color-mix(in_srgb,var(--success)_30%,transparent)] bg-[var(--success-soft)] text-[var(--success)]"
          )}>
            {uploadError || uploadMessage}
          </div>
        )}

        {/* Main content */}
        <div
          className="aira-focus-content flex min-h-0 flex-1 flex-col gap-4"
          data-composer-focused={composerFocused ? "true" : "false"}
        >
          {threadIsEmpty && !loading && !airaXLoading ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <AiraHomeStage
                question={question}
                setQuestion={setQuestion}
                busy={busy}
                loading={loading}
                octaState={octaState}
                octaMessage={octaMessage}
                octaProgress={octaProgress}
                octaInspector={octaInspector}
                onSubmit={handleSubmit}
                onComposerFocus={() => setComposerFocused(true)}
                attachedItems={attachedItems}
                onRemoveItem={onRemoveItem}
                onClearContext={onClearContext}
                onSaveBundle={onSaveBundle}
              />
              <AssistantWorkspaceLinks onUploadClick={() => uploadInputRef.current?.click()} />
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1 pt-2">
              {/* Thread */}
              {turns.map((turn, index) => (
                <ResearchTurnCard
                  key={`${turn.question}-${index}`}
                  turn={turn}
                  liveState={turn.streaming ? octaState : undefined}
                  liveLabel={turn.streaming ? (octaFlash ?? livePhase?.label ?? OCTA_STATUS[octaState].label) : undefined}
                  busy={busy}
                  onClarify={(text) => handleUnifiedAssistant(undefined, text)}
                />
              ))}

              {/* Workflow result */}
              {airaXResponse && (
                <WorkflowResultCard
                  response={airaXResponse}
                  approvalLoading={approvalLoading}
                  rejectionLoading={rejectionLoading}
                  onApprove={handleApproveAiraX}
                  onReject={handleRejectAiraX}
                />
              )}

              <div ref={threadBottomRef} />
            </div>
          )}

          {/* Composer — pinned as the static last child below the scrolling thread */}
          {!threadIsEmpty && (
            <div className="flex flex-col gap-2 pt-1">
              <OctaStatus
                state={octaState}
                message={octaMessage}
                progress={octaProgress}
                inspector={octaInspector}
                size="sm"
                className="px-1"
              />
              <form
                onSubmit={handleSubmit}
                className="aira-home-composer"
              >
                <ContextStack
                  items={attachedItems}
                  onRemoveItem={onRemoveItem}
                  onClearAll={onClearContext}
                  onSaveBundle={onSaveBundle}
                />
                <DocChips docs={uploadedDocs} onRemove={removeUploadedDocChip} />
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
              <div className="flex items-center justify-between gap-2 px-1 pt-3 pb-1 border-t border-[var(--border)]">
                <div className="flex min-w-0 items-center gap-2">
                  <AttachButton
                    onClick={() => uploadInputRef.current?.click()}
                    uploading={uploadLoading}
                    disabled={busy && !uploadLoading}
                  />
                  <span className="hidden items-center gap-1.5 text-xs text-[var(--text-subtle)] sm:inline-flex">
                    <ShieldAlert className="h-3.5 w-3.5 text-[var(--warning)]" />
                    Approval-gated when needed
                  </span>
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
            </div>
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
            onAttach={() => uploadInputRef.current?.click()}
            uploading={uploadLoading}
            uploadedDocs={uploadedDocs}
            onRemoveDoc={removeUploadedDocChip}
          />
        )}
      </div>
    </>
  );
}