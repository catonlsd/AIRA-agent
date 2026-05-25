"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ClipboardList,
  GitBranch,
  Hammer,
  History,
  MemoryStick,
  RefreshCw,
  Route,
  Search,
  ShieldCheck,
  UserCheck,
  Workflow,
} from "lucide-react";
import { getAiraXAgents } from "@/lib/api";
import { cn } from "@/lib/utils";

type Agent = {
  agent_name: string;
  name?: string;
  role: string;
  description: string;
  responsibilities: string[];
  capabilities?: string[];
  [key: string]: any;
};

type AgentTone = "blue" | "purple" | "green" | "orange" | "red" | "slate";

function getAgentIcon(agentName: string) {
  if (agentName === "planner_agent") {
    return <ClipboardList className="h-5 w-5" />;
  }

  if (agentName === "decision_agent") {
    return <Route className="h-5 w-5" />;
  }

  if (agentName === "execution_agent") {
    return <Hammer className="h-5 w-5" />;
  }

  if (agentName === "safety_agent") {
    return <ShieldCheck className="h-5 w-5" />;
  }

  if (agentName === "approval_agent") {
    return <UserCheck className="h-5 w-5" />;
  }

  if (agentName === "validation_agent") {
    return <GitBranch className="h-5 w-5" />;
  }

  if (agentName === "reflection_agent") {
    return <History className="h-5 w-5" />;
  }

  if (agentName === "memory_agent") {
    return <MemoryStick className="h-5 w-5" />;
  }

  return <BrainCircuit className="h-5 w-5" />;
}

function getAgentTone(agentName: string): AgentTone {
  if (agentName.includes("safety") || agentName.includes("approval")) {
    return "orange";
  }

  if (agentName.includes("execution")) {
    return "purple";
  }

  if (agentName.includes("validation")) {
    return "green";
  }

  if (agentName.includes("reflection")) {
    return "red";
  }

  if (agentName.includes("memory")) {
    return "slate";
  }

  return "blue";
}

function getToneClass(tone: AgentTone) {
  if (tone === "purple") {
    return "bg-[var(--secondary-soft)] text-[var(--secondary)]";
  }

  if (tone === "green") {
    return "bg-[var(--success-soft)] text-[var(--success)]";
  }

  if (tone === "orange") {
    return "bg-[var(--warning-soft)] text-[var(--warning)]";
  }

  if (tone === "red") {
    return "bg-[var(--danger-soft)] text-[var(--danger)]";
  }

  if (tone === "slate") {
    return "bg-[var(--surface-muted)] text-[var(--text-muted)]";
  }

  return "bg-[var(--accent-soft)] text-[var(--accent)]";
}

function formatAgentName(agentName: string) {
  return agentName
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getAgentDisplayName(agent: Agent) {
  return formatAgentName(agent.agent_name || agent.name || "agent");
}

function getAgentSearchText(agent: Agent) {
  return [
    agent.agent_name,
    agent.name,
    agent.role,
    agent.description,
    ...(agent.responsibilities || []),
    ...(agent.capabilities || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function MetricCard({
  label,
  value,
  description,
  icon,
}: {
  label: string;
  value: ReactNode;
  description: string;
  icon: ReactNode;
}) {
  return (
    <div className="sarvam-card rounded-[1.35rem] p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <p className="text-xs font-black uppercase tracking-[0.16em] text-[var(--text-subtle)]">
          {label}
        </p>

        <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] text-[var(--accent)]">
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

function AgentCapabilityChips({ agent }: { agent: Agent }) {
  const capabilities = agent.capabilities || [];

  if (capabilities.length === 0) {
    return null;
  }

  return (
    <div className="mt-4">
      <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
        Capabilities
      </p>

      <div className="flex flex-wrap gap-2">
        {capabilities.map((capability) => (
          <span
            key={capability}
            className="rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-3 py-1 text-xs font-bold text-[var(--text-muted)]"
          >
            {capability}
          </span>
        ))}
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const agentName = agent.agent_name || agent.name || "agent";
  const tone = getAgentTone(agentName);
  const responsibilities = Array.isArray(agent.responsibilities)
    ? agent.responsibilities
    : [];

  return (
    <article className="sarvam-card rounded-[1.5rem] p-5">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)]",
              getToneClass(tone)
            )}
          >
            {getAgentIcon(agentName)}
          </div>

          <div>
            <h3 className="text-lg font-black text-[var(--text-strong)]">
              {getAgentDisplayName(agent)}
            </h3>

            <p className="mt-1 font-mono text-[11px] text-[var(--text-subtle)]">
              {agentName}
            </p>
          </div>
        </div>

        <span
          className={cn(
            "rounded-full border border-[var(--border)] px-3 py-1 text-[11px] font-black uppercase tracking-wide",
            getToneClass(tone)
          )}
        >
          Active
        </span>
      </div>

      <div className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
        <p className="text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Role
        </p>

        <p className="mt-1 text-sm font-semibold text-[var(--text-strong)]">
          {agent.role || "No role recorded"}
        </p>
      </div>

      <p className="text-sm leading-7 text-[var(--text-muted)]">
        {agent.description || "No description available for this agent."}
      </p>

      <AgentCapabilityChips agent={agent} />

      <div className="mt-5">
        <p className="mb-2 text-xs font-black uppercase tracking-wide text-[var(--text-subtle)]">
          Responsibilities
        </p>

        {responsibilities.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-soft)] p-4 text-sm text-[var(--text-muted)]">
            No responsibilities recorded.
          </div>
        ) : (
          <div className="space-y-2">
            {responsibilities.map((responsibility) => (
              <div
                key={responsibility}
                className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] p-3"
              >
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" />

                <p className="text-sm leading-6 text-[var(--text-muted)]">
                  {responsibility}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentCount, setAgentCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [error, setError] = useState("");

  const loadAgents = useCallback(async () => {
    try {
      setLoading(true);

      const data = await getAiraXAgents();

      setAgents(data.agents || []);
      setAgentCount(data.agent_count || 0);
      setError("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load agents.";

      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const totalResponsibilities = useMemo(
    () =>
      agents.reduce(
        (total, agent) =>
          total +
          (Array.isArray(agent.responsibilities)
            ? agent.responsibilities.length
            : 0),
        0
      ),
    [agents]
  );

  const approvalAwareAgents = useMemo(
    () =>
      agents.filter((agent) => {
        const name = agent.agent_name || agent.name || "";

        return (
          name.includes("approval") ||
          name.includes("safety") ||
          name.includes("validation")
        );
      }).length,
    [agents]
  );

  const filteredAgents = useMemo(() => {
    const normalizedSearch = searchQuery.trim().toLowerCase();

    if (!normalizedSearch) {
      return agents;
    }

    return agents.filter((agent) =>
      getAgentSearchText(agent).includes(normalizedSearch)
    );
  }, [agents, searchQuery]);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-7xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-[var(--accent-glow)] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 left-1/3 h-64 w-64 rounded-full bg-[var(--secondary-glow)] blur-3xl" />

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
                <BrainCircuit className="h-3.5 w-3.5" />
                AIRA-X Multi-Agent System
              </div>

              <h1 className="aira-gradient-text text-4xl font-black tracking-tight">
                Agent Modules
              </h1>

              <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
                Inspect the specialist modules that plan, decide, execute,
                validate, reflect, remember, and enforce approval-aware safety
                across AIRA-X workflows.
              </p>

              <div className="mt-5 flex flex-wrap gap-3">
                <Link
                  href="/workflows"
                  className="inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-4 py-2.5 text-xs font-black text-[var(--accent-foreground)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5"
                >
                  <Workflow className="h-3.5 w-3.5" />
                  View Workflows
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>

                <Link
                  href="/approvals"
                  className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2.5 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                >
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Review Approvals
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
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
                Agent definitions are pulled from the AIRA-X backend registry.
              </p>
            </div>
          </div>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-5 py-3 text-sm font-medium text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
          Loading AIRA-X agents...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-[color-mix(in_srgb,var(--danger)_34%,transparent)] bg-[var(--danger-soft)] p-4 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Total Agents"
              value={agentCount}
              description="Registered specialist modules."
              icon={<BrainCircuit className="h-4 w-4" />}
            />

            <MetricCard
              label="Responsibilities"
              value={totalResponsibilities}
              description="Declared responsibilities across all agents."
              icon={<ClipboardList className="h-4 w-4" />}
            />

            <MetricCard
              label="Safety-Aware"
              value={approvalAwareAgents}
              description="Approval, safety, and validation modules."
              icon={<ShieldCheck className="h-4 w-4" />}
            />
          </section>

          <section className="sarvam-card rounded-[1.5rem] p-5">
            <SectionHeader
              icon={<Search className="h-4 w-4" />}
              title="Module Explorer"
              description={`Showing ${filteredAgents.length} of ${agents.length} registered agents.`}
              action={
                <button
                  type="button"
                  onClick={loadAgents}
                  className="inline-flex w-fit items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Refresh
                </button>
              }
            />

            <label className="relative block">
              <span className="sr-only">Search agent modules</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />

              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search agent name, role, capability, or responsibility..."
                className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-soft)] px-10 py-3 text-sm text-[var(--text-strong)] outline-none transition placeholder:text-[var(--text-subtle)] focus:border-[var(--border-strong)] focus:shadow-[var(--shadow-soft)]"
              />
            </label>

            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] px-4 py-2 text-xs font-black text-[var(--text-muted)] transition hover:bg-[var(--surface-hover)] hover:text-[var(--text-strong)]"
              >
                Clear Search
              </button>
            )}
          </section>

          {filteredAgents.length === 0 ? (
            <section className="aira-panel flex min-h-[260px] flex-col items-center justify-center rounded-[1.75rem] border-dashed p-10 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]">
                <Search className="h-5 w-5" />
              </div>

              <h2 className="text-xl font-black text-[var(--text-strong)]">
                No matching agents
              </h2>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--text-muted)]">
                Try searching a different agent name, role, capability, or
                responsibility.
              </p>
            </section>
          ) : (
            <section className="grid gap-4 lg:grid-cols-2">
              {filteredAgents.map((agent) => (
                <AgentCard
                  key={agent.agent_name || agent.name}
                  agent={agent}
                />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}