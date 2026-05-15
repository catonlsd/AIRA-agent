"use client";

import { useState } from "react";
import { Globe2, Cpu, Send, Sparkles } from "lucide-react";
import { CitationList } from "@/components/citation-list";
import { type ChatResponse, sendChat } from "@/lib/api";

type Turn = { question: string; response?: ChatResponse; error?: string };

export default function ChatPage() {
  const [question, setQuestion] = useState("");
  const [forceWeb, setForceWeb] = useState(false);
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    const trimmed = question.trim();
    if (!trimmed) return;

    setQuestion("");
    setLoading(true);
    setTurns((prev) => [...prev, { question: trimmed }]);

    try {
      const response = await sendChat(trimmed, forceWeb || undefined);

      setTurns((prev) =>
        prev.map((turn, i) =>
          i === prev.length - 1 ? { ...turn, response } : turn
        )
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Chat failed.";

      setTurns((prev) =>
        prev.map((turn, i) =>
          i === prev.length - 1 ? { ...turn, error: message } : turn
        )
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-6xl flex-col gap-6">
      <section className="sarvam-card fade-up relative overflow-hidden rounded-[2rem] p-6">
        <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-blue-200/50 blur-3xl" />

        <div className="relative z-10 flex items-start justify-between gap-4">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent">
              <Cpu className="h-3.5 w-3.5" />
              AI-powered research workspace
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
              AIRA Workspace
            </h1>

            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              Ask questions across your documents and receive answers enhanced by semantic retrieval and web intelligence.
            </p>
          </div>

          <div className="hidden rounded-full border border-blue-100 bg-white px-4 py-2 text-xs font-semibold text-slate-600 shadow-sm sm:block">
            {forceWeb ? "Web search enabled" : "Document-first mode"}
          </div>
        </div>
      </section>

      <div className="flex-1 space-y-5">
        {turns.length === 0 && (
          <div className="fade-up rounded-[2rem] border border-dashed border-blue-200 bg-white/80 p-10 text-center shadow-sm">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-accent">
              <Sparkles className="h-5 w-5" />
            </div>

            <h2 className="text-xl font-semibold text-slate-950">
              Start your research
            </h2>

            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              Upload documents, enable web search if needed, and ask questions.
            </p>
          </div>
        )}

        {turns.map((turn, index) => (
          <div
            key={`${turn.question}-${index}`}
            className="fade-up space-y-4"
          >
            <div className="ml-auto max-w-2xl rounded-[1.5rem] rounded-tr-md bg-accent px-5 py-3 text-sm leading-6 text-white shadow-lg shadow-blue-600/20">
              {turn.question}
            </div>

            {turn.error && (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {turn.error}
              </div>
            )}

            {turn.response && (
              <div className="sarvam-card rounded-[1.75rem] p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <div className="rounded-xl bg-blue-50 p-2 text-accent">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  AI Answer
                </div>

                <div className="whitespace-pre-wrap text-sm leading-7 text-ink">
                  {turn.response.answer
                  .replace(/^###\s?/gm, "")
                  .replace(/^##\s?/gm, "")
                  .replace(/^#\s?/gm, "")
                  .replace(/\*\*/g, "")
                  .replace(/Sources[\s\S]*/i, "")
                  .trim()
                  }
                  </div>

                {turn.response.citations.length > 0 && (
                  <div className="mt-5 rounded-[1.25rem] border border-blue-100 bg-blue-50/40 p-4">
                    <p className="mb-3 text-sm font-semibold text-slate-800">
                      Sources
                    </p>
                    <CitationList citations={turn.response.citations} />
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="fade-up w-fit rounded-full border border-blue-100 bg-white px-5 py-3 text-sm font-medium text-slate-600 shadow-sm">
            Researching sources...
          </div>
        )}
      </div>

      <form
        onSubmit={submit}
        className="sticky bottom-4 rounded-[2rem] border border-blue-100 bg-white/90 p-4 shadow-[0_18px_50px_rgba(37,99,235,0.12)] backdrop-blur-xl"
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question..."
          className="h-24 w-full resize-none rounded-[1.25rem] border border-blue-100 bg-[#f8fbff] p-4 text-sm text-slate-800 caret-blue-600 outline-none transition-all duration-300 placeholder:text-slate-400 focus:border-accent focus:bg-white focus:shadow-sm"
        />

        <div className="mt-3 flex items-center justify-between gap-3">
          <label className="flex cursor-pointer items-center gap-2 rounded-full bg-blue-50 px-3 py-2 text-sm font-medium text-slate-600">
            <input
              type="checkbox"
              checked={forceWeb}
              onChange={(event) => setForceWeb(event.target.checked)}
              className="accent-blue-600"
            />
            <Globe2 className="h-4 w-4 text-accent" />
            Include web search
          </label>

          <button
            disabled={loading}
            className="group inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Send className="h-4 w-4 transition-all duration-700 ease-out group-hover:-translate-y-2 group-hover:translate-x-3 group-hover:rotate-12 group-hover:opacity-0" />
            Send
          </button>
        </div>
      </form>
    </div>
  );
}