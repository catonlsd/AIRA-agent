"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Code2,
  Cpu,
  Database,
  FileText,
  GitBranch,
  Globe2,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Terminal,
  Wrench,
  XCircle,
} from "lucide-react";
import { getAiraXTools } from "@/lib/api";
import { cn } from "@/lib/utils";

type ToolPolicy = {
  risk_level?: string;
  requires_approval?: boolean;
  description?: string;
  [key: string]: any;
};

type Tool = {
  tool_name: string;
  name?: string;
  description: string;
  actions: string[];
  examples: string[];
  policy?: Record<string, ToolPolicy>;
  [key: string]: any;
};

type ToolTone = "accent" | "secondary" | "success" | "warning" | "danger" | "slate";
type RiskFilter = "all" | "safe" | "sensitive" | "dangerous" | "approval_required";

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatToolName(toolName: string) {
  return toolName
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getToolDisplayName(tool: Tool) {
  return formatToolName(tool.tool_name || tool.name || "tool");
}

function getToolIcon(toolName: string) {
  const normalizedName = toolName.toLowerCase();

  if (normalizedName.includes("shell")) {
    return <Terminal className="h-5 w-5" />;
  }

  if (normalizedName.includes("file") || normalizedName.includes("document")) {
    return <FileText className="h-5 w-5" />;
  }

  if (normalizedName.includes("python") || normalizedName.includes("code")) {
    return <Code2 className="h-5 w-5" />;
  }

  if (normalizedName.includes("git")) {
    return <GitBranch className="h-5 w-5" />;
  }

  if (normalizedName.includes("web") || normalizedName.includes("search")) {
    return <Globe2 className="h-5 w-5" />;
  }

  if (normalizedName.includes("memory") || normalizedName.includes("storage")) {
    return <Database className="h-5 w-5" />;
  }

  return <Wrench className="h-5 w-5" />;
}

function getToolTone(toolName: string): ToolTone {
  const normalizedName = toolName.toLowerCase();

  if (normalizedName.includes("git") || normalizedName.includes("shell")) {
    return "warning";
  }

  if (normalizedName.includes("python") || normalizedName.includes("code")) {
    return "secondary";
  }

  if (normalizedName.includes("file") || normalizedName.includes("document")) {
    return "accent";
  }

  if (normalizedName.includes("web") || normalizedName.includes("search")) {
    return "success";
  }

  return "accent";
}

function getToneSurface(tone: ToolTone) {
  if (tone === "secondary") {
    return "bg-[var(--secondary-soft)] text-[var(--secondary)]";
  }

  if (tone === "success") {
    return "bg-[var(--success-soft)] text-[var(--success)]";
  }

  if (tone === "warning") {
    return "bg-[var(--warning-soft)] text-[var(--warning)]";
  }

  if (tone === "danger") {
    return "bg-[var(--danger-soft)] text-[var(--danger)]";
  }

  if (tone === "slate") {
    return "bg-[var(--surface-muted)] text-[var(--text-muted)]";
  }

  return "bg-[var(--accent-soft)] text-[var(--accent)]";
}

function normalizeRiskLevel(value?: string) {
  return (value || "unknown").toLowerCase();
}

function getRiskBadgeClass(riskLevel?: string) {
  const normalizedRisk = normalizeRiskLevel(riskLevel);

  if (normalizedRisk === "safe") {
    return "status-success";
  }

  if (normalizedRisk === "sensitive") {
    return "status-warning";
  }

  if (normalizedRisk === "dangerous") {
    return "status-danger";
  }

  return "status-info";
}

function getRiskIcon(riskLevel?: string) {
  const normalizedRisk = normalizeRiskLevel(riskLevel);

  if (normalizedRisk === "safe") {
    return <CheckCircle2 className="h-3.5 w-3.5" />;
  }

  if (normalizedRisk === "sensitive") {
    return <ShieldAlert className="h-3.5 w-3.5" />;
  }

  if (normalizedRisk === "dangerous") {
    return <XCircle className="h-3.5 w-3.5" />;
  }

  return <ShieldCheck className="h-3.5 w-3.5" />;
}

function getPolicyEntries(tool: Tool) {
  return Object.entries(tool.policy || {});
}

function toolHasRisk(tool: Tool, riskLevel: string) {
  return getPolicyEntries(tool).some(
    ([, policy]) => normalizeRiskLevel(policy.risk_level) === riskLevel
  );
}

function toolRequiresApproval(tool: Tool) {
  return getPolicyEntries(tool).some(
    ([, policy]) => policy.requires_approval === true
  );
}

function getToolSearchText(tool: Tool) {
  return [
    tool.tool_name,
    tool.name,
    tool.description,
    ...(tool.actions || []),
    ...(tool.examples || []),
    ...getPolicyEntries(tool).flatMap(([action, policy]) => [
      action,
      policy.risk_level,
      policy.description,
      policy.requires_approval ? "requires approval approval required" : "no approval",
    ]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getFilteredTools(
  tools: Tool[],
  searchQuery: string,
  riskFilter: RiskFilter
) {
  const normalizedSearch = searchQuery.trim().toLowerCase();

  return tools.filter((tool) => {
    const matchesSearch =
      !normalizedSearch || getToolSearchText(tool).includes(normalizedSearch);

    const matchesRisk =
      riskFilter === "all" ||
      (riskFilter === "approval_required" && toolRequiresApproval(tool)) ||
      toolHasRisk(tool, riskFilter);

    return matchesSearch && matchesRisk;
  });
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

function MetricCard({
  label,
  value,
  description,
  icon,
  tone = "accent",
}: {
  label: string;
  value: ReactNode;
  description: string;
  icon: ReactNode;
  tone?: ToolTone;
}) {
  return (
    <div className="sarvam-card rounded-[1.35rem] p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
          {label}
        </p>

        <div
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)]",
            getToneSurface(tone)
          )}
        >
          {icon}
        </div>
      </div>

      <h2 className="text-3xl font-black text-[var(--text-strong)]">
        {value}
      </h2>

      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        {description}
      </p>
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
  description: string;
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

          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">
            {description}
          </p>
        </div>
      </div>

      {action}
    </div>
  );
}

function ActionChips({ actions }: { actions: string[] }) {
  if (!Array.isArray(actions) || actions.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
        No actions registered.
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((action) => (
        <span
          key={action}
          className="rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1 text-xs font-bold text-[var(--text-muted)]"
        >
          {action}
        </span>
      ))}
    </div>
  );
}

function PolicyPanel({ tool }: { tool: Tool }) {
  const policyEntries = getPolicyEntries(tool);

  if (policyEntries.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
        No explicit risk policy registered for this tool.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {policyEntries.map(([action, policy]) => (
        <div
          key={action}
          className="rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4"
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-xs font-black text-[var(--text-strong)]">
              {action}
            </p>

            <div className="flex flex-wrap gap-2">
              <RunBadge className={getRiskBadgeClass(policy.risk_level)}>
                {getRiskIcon(policy.risk_level)}
                {policy.risk_level || "unknown"}
              </RunBadge>

              <RunBadge
                className={
                  policy.requires_approval
                    ? "status-warning"
                    : "status-success"
                }
              >
                {policy.requires_approval ? (
                  <ShieldAlert className="h-3.5 w-3.5" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                {policy.requires_approval ? "Approval required" : "No approval"}
              </RunBadge>
            </div>
          </div>

          <p className="text-sm leading-6 text-[var(--text-muted)]">
            {policy.description || "No policy description recorded."}
          </p>
        </div>
      ))}
    </div>
  );
}

function ExamplesPanel({ examples }: { examples: string[] }) {
  if (!Array.isArray(examples) || examples.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
        No examples registered.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {examples.map((example) => (
        <pre
          key={example}
          className="overflow-auto whitespace-pre-wrap rounded-2xl p-3 font-mono text-xs leading-6"
        >
          {example}
        </pre>
      ))}
    </div>
  );
}

function ToolCard({ tool }: { tool: Tool }) {
  const toolName = tool.tool_name || tool.name || "tool";
  const tone = getToolTone(toolName);
  const policyEntries = getPolicyEntries(tool);
  const approvalRequiredCount = policyEntries.filter(
    ([, policy]) => policy.requires_approval
  ).length;

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)]",
              getToneSurface(tone)
            )}
          >
            {getToolIcon(toolName)}
          </div>

          <div>
            <h3 className="text-lg font-black text-[var(--text-strong)]">
              {getToolDisplayName(tool)}
            </h3>

            <p className="mt-1 font-mono text-[11px] text-[var(--text-subtle)]">
              {toolName}
            </p>
          </div>
        </div>

        <RunBadge
          className={
            approvalRequiredCount > 0 ? "status-warning" : "status-success"
          }
        >
          {approvalRequiredCount > 0 ? (
            <ShieldAlert className="h-3.5 w-3.5" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" />
          )}
          {approvalRequiredCount > 0
            ? `${approvalRequiredCount} gated`
            : "Ungated"}
        </RunBadge>
      </div>

      <p className="text-sm leading-7 text-[var(--text-muted)]">
        {tool.description || "No description available for this tool."}
      </p>

      <div className="mt-5">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Actions
        </p>

        <ActionChips actions={tool.actions || []} />
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          <ShieldCheck className="h-3.5 w-3.5" />
          Risk Policy
        </div>

        <PolicyPanel tool={tool} />
      </div>

      <div className="mt-5">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Example Usage
        </p>

        <ExamplesPanel examples={tool.examples || []} />
      </div>
    </article>
  );
}

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [toolCount, setToolCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadTools = useCallback(async () => {
    try {
      setLoading(true);

      const data = await getAiraXTools();

      setTools(data.tools || []);
      setToolCount(data.tool_count || 0);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load tools.";

      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTools();
  }, [loadTools]);

  const totalActions = useMemo(
    () =>
      tools.reduce(
        (total, tool) => total + (Array.isArray(tool.actions) ? tool.actions.length : 0),
        0
      ),
    [tools]
  );

  const totalPolicyEntries = useMemo(
    () => tools.reduce((total, tool) => total + getPolicyEntries(tool).length, 0),
    [tools]
  );

  const approvalRequiredActions = useMemo(
    () =>
      tools.reduce(
        (total, tool) =>
          total +
          getPolicyEntries(tool).filter(
            ([, policy]) => policy.requires_approval === true
          ).length,
        0
      ),
    [tools]
  );

  const highRiskActions = useMemo(
    () =>
      tools.reduce(
        (total, tool) =>
          total +
          getPolicyEntries(tool).filter(([, policy]) =>
            ["sensitive", "dangerous"].includes(
              normalizeRiskLevel(policy.risk_level)
            )
          ).length,
        0
      ),
    [tools]
  );

  const filteredTools = useMemo(
    () => getFilteredTools(tools, searchQuery, riskFilter),
    [tools, searchQuery, riskFilter]
  );

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />

        <div className="relative z-10">
          <Link
            href="/settings"
            className="mb-5 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to System Console
          </Link>

          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div>
              <div className="aira-chip mb-4 px-3 py-1.5 text-xs font-bold">
                <Cpu className="h-3.5 w-3.5" />
                AIRA-X Execution Capability Layer
              </div>

              <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
                Tool Layer
              </h1>

              <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
                Inspect the tools AIRA-X can use to complete real tasks. Each
                module exposes allowed actions, example calls, approval
                requirements, and risk policies before execution.
              </p>
            </div>

            <div className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-soft)] p-4">
              <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
                Registry Status
              </p>

              <div className="mt-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-black status-success">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Loaded from backend
              </div>

              <p className="mt-3 text-xs leading-5 text-[var(--text-muted)]">
                Tool definitions and risk policies are pulled from the AIRA-X
                backend registry.
              </p>
            </div>
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading AIRA-X tools...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Total Tools"
              value={formatNumber(toolCount)}
              description="Registered execution modules."
              icon={<Wrench className="h-4 w-4" />}
              tone="accent"
            />

            <MetricCard
              label="Available Actions"
              value={formatNumber(totalActions)}
              description="Actions exposed by all tools."
              icon={<Terminal className="h-4 w-4" />}
              tone="secondary"
            />

            <MetricCard
              label="Policy Entries"
              value={formatNumber(totalPolicyEntries)}
              description="Action-level risk policies."
              icon={<ShieldCheck className="h-4 w-4" />}
              tone="success"
            />

            <MetricCard
              label="Approval-Gated"
              value={formatNumber(approvalRequiredActions)}
              description={`${formatNumber(highRiskActions)} sensitive or dangerous actions.`}
              icon={<LockKeyhole className="h-4 w-4" />}
              tone="warning"
            />
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <SectionHeader
              icon={<Search className="h-4 w-4" />}
              title="Tool Explorer"
              description={`Showing ${formatNumber(filteredTools.length)} of ${formatNumber(
                tools.length
              )} registered tools.`}
              action={
                <button
                  type="button"
                  onClick={loadTools}
                  className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Refresh
                </button>
              }
            />

            <div className="grid gap-3 lg:grid-cols-[1fr_240px]">
              <label className="relative block">
                <span className="sr-only">Search tools</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

                <input
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Search tool name, action, policy, example..."
                  className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm text-[var(--text-strong)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
                />
              </label>

              <label className="relative block">
                <span className="sr-only">Risk filter</span>
                <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

                <select
                  value={riskFilter}
                  onChange={(event) =>
                    setRiskFilter(event.target.value as RiskFilter)
                  }
                  className="w-full appearance-none rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm font-semibold text-[var(--text-strong)] outline-none transition focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
                >
                  <option value="all">All risk levels</option>
                  <option value="safe">Safe actions</option>
                  <option value="sensitive">Sensitive actions</option>
                  <option value="dangerous">Dangerous actions</option>
                  <option value="approval_required">Approval required</option>
                </select>
              </label>
            </div>

            {(searchQuery || riskFilter !== "all") && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery("");
                  setRiskFilter("all");
                }}
                className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                Clear Filters
              </button>
            )}
          </section>

          {filteredTools.length === 0 ? (
            <section className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                <Search className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No matching tools
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Try searching a different tool name, action, risk level, policy,
                or example.
              </p>
            </section>
          ) : (
            <section className="grid gap-4 xl:grid-cols-2">
              {filteredTools.map((tool) => (
                <ToolCard
                  key={tool.tool_name || tool.name}
                  tool={tool}
                />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}
