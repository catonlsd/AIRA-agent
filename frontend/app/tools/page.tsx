"use client";

import { useEffect, useState } from "react";
import { Wrench, Cpu, Terminal, FileText, Code2 } from "lucide-react";
import { getAiraXTools } from "@/lib/api";

type Tool = {
  tool_name: string;
  description: string;
  actions: string[];
  examples: string[];
};

function getToolIcon(toolName: string) {
  if (toolName === "shell_tool") return <Terminal className="h-5 w-5" />;
  if (toolName === "file_tool") return <FileText className="h-5 w-5" />;
  if (toolName === "python_tool") return <Code2 className="h-5 w-5" />;

  return <Wrench className="h-5 w-5" />;
}

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [toolCount, setToolCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadTools() {
      try {
        const data = await getAiraXTools();

        setTools(data.tools || []);
        setToolCount(data.tool_count || 0);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to load tools.";

        setError(message);
      } finally {
        setLoading(false);
      }
    }

    loadTools();
  }, []);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-purple-200/50 blur-3xl" />

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-purple-100 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-700">
            <Cpu className="h-3.5 w-3.5" />
            AIRA-X Execution Toolkit
          </div>

          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Tools Registry
          </h1>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            These are the tools AIRA-X can use to execute real tasks. The
            registry tells the system which tools exist, what actions are
            allowed, and how each tool can be used.
          </p>
        </div>
      </section>

      {loading && (
        <div className="w-fit rounded-full border border-purple-100 bg-white px-5 py-3 text-sm font-medium text-purple-700 shadow-sm">
          Loading AIRA-X tools...
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && (
        <section className="grid gap-4">
          <div className="sarvam-card rounded-[1.5rem] p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-500">
                  Available Tools
                </p>
                <h2 className="text-2xl font-semibold text-slate-950">
                  {toolCount}
                </h2>
              </div>

              <div className="rounded-2xl bg-purple-50 p-3 text-purple-600">
                <Wrench className="h-6 w-6" />
              </div>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {tools.map((tool) => (
              <div
                key={tool.tool_name}
                className="sarvam-card rounded-[1.5rem] p-5"
              >
                <div className="mb-4 flex items-center gap-3">
                  <div className="rounded-2xl bg-purple-50 p-3 text-purple-600">
                    {getToolIcon(tool.tool_name)}
                  </div>

                  <div>
                    <h3 className="font-semibold text-slate-950">
                      {tool.tool_name}
                    </h3>
                    <p className="text-xs text-slate-500">Execution Tool</p>
                  </div>
                </div>

                <p className="text-sm leading-6 text-slate-600">
                  {tool.description}
                </p>

                <div className="mt-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Allowed Actions
                  </p>

                  <div className="flex flex-wrap gap-2">
                    {tool.actions.map((action) => (
                      <span
                        key={action}
                        className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"
                      >
                        {action}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="mt-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Examples
                  </p>

                  <div className="space-y-2">
                    {tool.examples.map((example) => (
                      <code
                        key={example}
                        className="block rounded-xl bg-slate-950 px-3 py-2 text-xs text-slate-100"
                      >
                        {example}
                      </code>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}