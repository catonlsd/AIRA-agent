import {
  Activity,
  Brain,
  Database,
  FileText,
  Globe,
  KeyRound,
  MemoryStick,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const statusCards = [
  {
    title: "Backend API",
    value: "Connected",
    description: API_URL,
    icon: Server,
    status: "Online",
  },
  {
    title: "LLM Provider",
    value: "Groq",
    description: "Primary generation model configured from backend environment.",
    icon: Brain,
    status: "Active",
  },
  {
    title: "Web Search",
    value: "Tavily",
    description: "Used when Include web search is enabled in chat.",
    icon: Globe,
    status: "Ready",
  },
  {
    title: "Memory",
    value: "Enabled",
    description: "Stores recent conversation context for better follow-up answers.",
    icon: MemoryStick,
    status: "On",
  },
];

const configItems = [
  {
    label: "Documents",
    value: "PDF, TXT, DOCX, Markdown",
    icon: FileText,
  },
  {
    label: "Retrieval Mode",
    value: "Document RAG + Optional Web Search",
    icon: Search,
  },
  {
    label: "Vector Store",
    value: "Local persistent vector index",
    icon: Database,
  },
  {
    label: "Security",
    value: "Environment-based API keys",
    icon: KeyRound,
  },
];

const retrievalSettings = [
  { label: "Chunk Size", value: "1000 tokens" },
  { label: "Chunk Overlap", value: "150 tokens" },
  { label: "Retrieval K", value: "6 sources" },
  { label: "Max Upload Size", value: "10 MB" },
];

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-7">
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10 flex items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
              <Activity className="h-3.5 w-3.5" />
              Architecture
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              About AIRA
            </h1>

            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
              Explore the core systems powering AIRA, including document retrieval,
              web research, memory, citations, deployment, and LLM-based answer generation.
            </p>
          </div>

          
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statusCards.map((card) => {
          const Icon = card.icon;

          return (
            <div
              key={card.title}
              className="group sarvam-card fade-up rounded-[1.5rem] p-5 transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-blue-100/70"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="rounded-2xl bg-blue-50 p-3 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-3">
                  <Icon className="h-5 w-5" />
                </div>

                <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-accent">
                  {card.status}
                </span>
              </div>

              <h2 className="mt-4 text-sm font-medium text-slate-500">
                {card.title}
              </h2>

              <p className="mt-1 text-xl font-semibold text-slate-950">
                {card.value}
              </p>

              <p className="mt-2 text-xs leading-5 text-slate-500">
                {card.description}
              </p>
            </div>
          );
        })}
      </section>

      <section className="grid gap-6 lg:grid-cols-3">
        <div className="sarvam-card fade-up rounded-[2rem] p-6 lg:col-span-2">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-blue-50 p-3 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-3">
              <Activity className="h-5 w-5" />
            </div>

            <div>
              <h2 className="text-lg font-semibold text-slate-950">
                System Capabilities
              </h2>
              <p className="text-sm text-slate-500">
                Core modules enabled in this AI research workflow.
              </p>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {configItems.map((item) => {
              const Icon = item.icon;

              return (
                <div
                  key={item.label}
                  className="group rounded-[1.25rem] border border-blue-100 bg-blue-50/40 p-4 transition-all duration-300 hover:-translate-y-1 hover:bg-blue-50 hover:shadow-md"
                >
                  <div className="flex items-center gap-3">
                    <Icon className="h-4 w-4 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-6" />
                    <p className="text-sm font-semibold text-slate-800">
                      {item.label}
                    </p>
                  </div>

                  <p className="mt-2 text-sm text-slate-600">
                    {item.value}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        <div className="sarvam-card fade-up rounded-[2rem] p-6">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-blue-50 p-3 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-3">
              <SlidersHorizontal className="h-5 w-5" />
            </div>

            <div>
              <h2 className="text-lg font-semibold text-slate-950">
                Retrieval Info
              </h2>

              <p className="text-sm text-slate-500">Current RAG defaults.</p>
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {retrievalSettings.map((setting) => (
              <div
                key={setting.label}
                className="flex items-center justify-between rounded-[1.25rem] border border-blue-100 bg-white px-4 py-3 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md hover:border-blue-200"
              >
                <span className="text-sm text-slate-600">
                  {setting.label}
                </span>
                <span className="text-sm font-semibold text-slate-950">
                  {setting.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="sarvam-card fade-up rounded-[2rem] p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-blue-50 p-3 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-3">
            <ShieldCheck className="h-5 w-5" />
          </div>

          <div>
            <h2 className="text-lg font-semibold text-slate-950">
              Deployment Notes
            </h2>
            <p className="text-sm text-slate-500">
              Environment variables required for production deployment.
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {[
            ["Frontend", "NEXT_PUBLIC_API_URL"],
            ["LLM", "GROQ_API_KEY"],
            ["Web Search", "TAVILY_API_KEY"],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-[1.25rem] border border-blue-100 bg-blue-50/40 p-4 transition-all duration-300 hover:-translate-y-1 hover:bg-blue-50 hover:shadow-md"
            >
              <p className="text-sm font-semibold text-slate-800">
                {label}
              </p>
              <code className="mt-2 block rounded-xl bg-white px-3 py-2 text-xs text-slate-600">
                {value}
              </code>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}