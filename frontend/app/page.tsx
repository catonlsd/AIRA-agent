import Link from "next/link";
import {
  ArrowRight,
  Brain,
  Database,
  FileSearch,
  Globe2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

const metrics = [
  ["7", "specialized agents"],
  ["4", "document formats"],
  ["100%", "source-first answers"],
];

const features = [
  [FileSearch, "RAG QnA", "Semantic retrieval over uploaded documents."],
  [Globe2, "Web Agent", "Uses web search only when needed or requested."],
  [Database, "Memory", "SQLite chat history and user preferences."],
  [ShieldCheck, "Citations", "Document and web sources stay visible."],
];

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-8">
        <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-blue-200/40 blur-3xl" />
        <div className="absolute -bottom-24 left-20 h-64 w-64 rounded-full bg-sky-100/70 blur-3xl" />

        <div className="relative z-10 grid gap-8 lg:grid-cols-[1.25fr_0.75fr]">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-4 py-2 text-sm font-semibold text-accent">
              <Sparkles className="h-4 w-4" />
              Multi-Agent Research Platform
            </div>

            <h1 className="max-w-3xl text-5xl font-semibold tracking-tight text-slate-950">
              AIRA for documents, web search and cited answers.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-600">
              Upload documents, ask questions, retrieve answers
              and enhance research with real-time web intelligence.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/upload"
                className="group inline-flex items-center gap-2 rounded-full bg-accent px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-600/25"
              >
                Upload documents
                <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
              </Link>

              <Link
                href="/chat"
                className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition-all duration-300 hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50 hover:text-accent"
              >
                Open chat
              </Link>
            </div>
          </div>

          <div className="grid gap-3">
            {metrics.map(([value, label]) => (
              <div
                key={label}
                className="rounded-3xl border border-blue-100 bg-white/80 p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-lg"
              >
                <div className="text-3xl font-semibold text-accent">
                  {value}
                </div>

                <div className="mt-1 text-sm text-slate-500">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        {features.map(([Icon, title, body]) => {
          const Component = Icon as typeof FileSearch;

          return (
            <div
              key={String(title)}
              className="group sarvam-card fade-up rounded-[1.5rem] p-5 transition-all duration-300 hover:-translate-y-1"
            >
              <div className="mb-4 inline-flex rounded-2xl bg-blue-50 p-3 text-accent transition-all duration-300 group-hover:scale-110">
                <Component className="h-5 w-5 transition-transform duration-300 group-hover:rotate-3" />
              </div>

              <h2 className="font-semibold text-slate-950">{String(title)}</h2>

              <p className="mt-2 text-sm leading-6 text-slate-500">
                {String(body)}
              </p>
            </div>
          );
        })}
      </section>

      <section className="sarvam-card fade-up rounded-[2rem] p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-accent">
              <Brain className="h-4 w-4" />
              Designed for intelligent research workflows
            </div>

            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Demonstrates practical AI product engineering across FastAPI,
              Next.js, RAG, LLM integration, web search, document processing,
              memory and citation-aware answer generation.
            </p>
          </div>

          <Link
            href="/settings"
            className="inline-flex w-fit items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-5 py-3 text-sm font-semibold text-accent transition hover:-translate-y-0.5 hover:bg-blue-100"
          >
            View Architecture
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}