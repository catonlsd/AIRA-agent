"use client";

import { useEffect, useState } from "react";
import {
  BrainCircuit,
  ClipboardList,
  GitBranch,
  Hammer,
  History,
  MemoryStick,
  Route,
  ShieldCheck,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { getAiraXAgents } from "@/lib/api";

type Agent = {
  agent_name: string;
  role: string;
  description: string;
  responsibilities: string[];
};

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

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentCount, setAgentCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAgents() {
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
  }

  useEffect(() => {
    loadAgents();
  }, []);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
            <BrainCircuit className="h-3.5 w-3.5" />
            AIRA-X Multi-Agent System
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Agent Registry
          </h1>

          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            These are the specialized agents that plan, decide, execute,
            validate, reflect, remember, and control AIRA-X workflows.
          </p>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-blue-700 shadow-sm">
          Loading AIRA-X agents...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <section className="grid gap-4 md:grid-cols-3">
            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Total Agents
              </p>

              <h2 className="mt-1 text-3xl font-semibold text-slate-950">
                {agentCount}
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Core Capability
              </p>

              <h2 className="mt-1 text-xl font-semibold text-blue-700">
                Execution
              </h2>
            </div>

            <div className="sarvam-card rounded-[1.5rem] p-5">
              <p className="text-sm font-semibold text-slate-500">
                Architecture Type
              </p>

              <h2 className="mt-1 text-xl font-semibold text-purple-700">
                Multi-Agent
              </h2>
            </div>
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            {agents.map((agent) => (
              <div
                key={agent.agent_name}
                className="sarvam-card rounded-[1.5rem] p-5"
              >
                <div className="mb-4 flex items-start gap-3">
                  <div className="rounded-2xl bg-blue-50 p-3 text-blue-600">
                    {getAgentIcon(agent.agent_name)}
                  </div>

                  <div>
                    <h3 className="font-semibold text-slate-950">
                      {agent.agent_name}
                    </h3>

                    <p className="mt-1 inline-flex rounded-full bg-purple-50 px-3 py-1 text-xs font-semibold text-purple-700">
                      {agent.role}
                    </p>
                  </div>
                </div>

                <p className="text-sm leading-6 text-slate-600">
                  {agent.description}
                </p>

                <div className="mt-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Responsibilities
                  </p>

                  <div className="space-y-2">
                    {agent.responsibilities.map((responsibility) => (
                      <div
                        key={responsibility}
                        className="flex items-start gap-2 rounded-xl bg-slate-50 p-3 text-sm text-slate-600"
                      >
                        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-600" />
                        <span>{responsibility}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}