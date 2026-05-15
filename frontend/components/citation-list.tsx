import { ExternalLink, FileText, Globe2 } from "lucide-react";
import type { Citation } from "@/lib/api";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;

  return (
    <div className="space-y-3">
      {citations.map((citation, index) => {
        const isWeb = citation.source_type?.toLowerCase() === "web";
        const Icon = isWeb ? Globe2 : FileText;

        return (
          <div
            key={`${citation.title}-${index}`}
            className="group rounded-[1.25rem] border border-blue-100 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-lg hover:shadow-blue-100/70"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-blue-50 p-2 text-accent transition-all duration-300 group-hover:scale-110 group-hover:rotate-3">
                  <Icon className="h-4 w-4" />
                </div>

                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-accent">
                      {citation.source_type}
                    </span>

                    <span className="text-sm font-semibold text-slate-900">
                      Source {index + 1}
                    </span>
                  </div>

                  <p className="mt-2 text-sm font-medium leading-5 text-slate-800">
                    {citation.title}
                  </p>
                </div>
              </div>

              {citation.url && (
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-accent transition-all duration-300 hover:-translate-y-0.5 hover:bg-blue-100"
                >
                  Open
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>

            {!isWeb && (
              <div className="mt-3 text-xs font-medium text-slate-400">
                Page {citation.page ?? "n/a"}
              </div>
            )}

            {citation.snippet && (
              <p className="mt-3 rounded-2xl bg-blue-50/40 p-3 text-sm leading-6 text-slate-600">
                {citation.snippet
                ?.replace(/^###\s?/gm, "")
                .replace(/^##\s?/gm, "")
                .replace(/^#\s?/gm, "")
                .replace(/\*\*/g, "")
                }
                </p>
            )}
          </div>
        );
      })}
    </div>
  );
}