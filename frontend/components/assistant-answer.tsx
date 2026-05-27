"use client";

import { CheckCircle2 } from "lucide-react";
import {
  formatInlineText,
  isMultiTaskAnswer,
  parseListItems,
  parseMultiTaskAnswer,
  parseStructuredSections,
  partitionAnswerSections,
  sectionUsesList,
  splitParagraphs,
  stripTrailingSources,
  type AnswerSection,
  type ParsedMultiTask,
} from "@/lib/format-answer";
import { TechnicalDetailsPanel } from "@/components/technical-details";
import { cn } from "@/lib/utils";

type AssistantAnswerContentProps = {
  answer: string;
  className?: string;
};

function InlineText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);

  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-black text-[var(--text-strong)]">
              {part.slice(2, -2)}
            </strong>
          );
        }

        return <span key={index}>{part}</span>;
      })}
    </>
  );
}

function AnswerCodeBlock({
  value,
  variant = "code",
}: {
  value: string;
  variant?: "code" | "output";
}) {
  return (
    <pre
      className={cn(
        "max-h-80 overflow-auto whitespace-pre-wrap rounded-xl border p-4 text-xs leading-6",
        variant === "output"
          ? "border-[var(--border)] bg-[var(--surface-muted)] font-mono text-[var(--text)]"
          : "border-[color-mix(in_srgb,var(--accent)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent)_6%,transparent)] font-mono text-[var(--text-strong)]"
      )}
    >
      {value.trim()}
    </pre>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2 pl-1">
      {items.map((item, index) => (
        <li
          key={index}
          className="flex gap-2 text-sm leading-6 text-[var(--text)]"
        >
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />
          <span>
            <InlineText text={item} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function ParagraphBlock({ text }: { text: string }) {
  const paragraphs = splitParagraphs(text);

  if (paragraphs.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          className="text-sm leading-7 text-[var(--text)]"
        >
          <InlineText text={formatInlineText(paragraph)} />
        </p>
      ))}
    </div>
  );
}

function SectionBlock({ section }: { section: AnswerSection }) {
  if (!section.title) {
    return <ParagraphBlock text={section.content} />;
  }

  const useList = sectionUsesList(section.title, section.content);
  const listItems = useList ? parseListItems(section.content) : [];

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-4">
      <p className="text-[11px] font-black uppercase tracking-[0.14em] text-[var(--text-subtle)]">
        {section.title}
      </p>

      <div className="mt-3">
        {useList && listItems.length > 0 ? (
          <BulletList items={listItems} />
        ) : section.variant === "code" || section.variant === "output" ? (
          <AnswerCodeBlock
            value={section.content}
            variant={section.variant === "output" ? "output" : "code"}
          />
        ) : section.variant === "meta" ? (
          <p className="whitespace-pre-wrap font-mono text-xs leading-6 text-[var(--text-muted)]">
            {section.content}
          </p>
        ) : (
          <ParagraphBlock text={section.content} />
        )}
      </div>
    </div>
  );
}

function StructuredTechnicalSections({ sections }: { sections: AnswerSection[] }) {
  if (sections.length === 0) {
    return null;
  }

  return (
    <TechnicalDetailsPanel className="mt-3">
      <div className="space-y-3">
        {sections.map((section, index) => (
          <div
            key={`${section.title}-${index}`}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3"
          >
            {section.title ? (
              <p className="text-[10px] font-black uppercase tracking-wide text-[var(--text-subtle)]">
                {section.title}
              </p>
            ) : null}
            <div className={section.title ? "mt-2" : undefined}>
              {sectionUsesList(section.title, section.content) ? (
                <BulletList items={parseListItems(section.content)} />
              ) : (
                <p className="whitespace-pre-wrap font-mono text-xs leading-6 text-[var(--text-muted)]">
                  {section.content}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </TechnicalDetailsPanel>
  );
}

function StructuredAnswer({ answer }: { answer: string }) {
  const sections = parseStructuredSections(answer);

  if (!sections) {
    return <ParagraphBlock text={answer} />;
  }

  const { visible, technical } = partitionAnswerSections(sections);

  return (
    <div className="space-y-3">
      {visible.map((section, index) => (
        <SectionBlock key={`${section.title}-${index}`} section={section} />
      ))}
      <StructuredTechnicalSections sections={technical} />
    </div>
  );
}

function MultiTaskIntro({ intro }: { intro: string }) {
  if (!intro.trim()) {
    return null;
  }

  return (
    <div className="rounded-xl border border-[color-mix(in_srgb,var(--accent)_24%,transparent)] bg-[var(--accent-soft)] px-4 py-3">
      <p className="text-sm font-semibold leading-6 text-[var(--text-strong)]">
        <InlineText text={intro} />
      </p>
    </div>
  );
}

function MultiTaskBody({ body }: { body: string }) {
  return <StructuredAnswer answer={body} />;
}

function MultiTaskCard({
  task,
}: {
  task: ParsedMultiTask["tasks"][number];
}) {
  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface-soft)] p-4">
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] text-xs font-black text-[var(--accent)]">
          {task.index}
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-black text-[var(--text-strong)]">
            {task.title}
          </p>
        </div>
      </div>

      <div className="border-t border-[var(--border)] pt-3">
        <MultiTaskBody body={task.body} />
      </div>
    </article>
  );
}

function MultiTaskSummary({ summary }: { summary: string }) {
  if (!summary.trim()) {
    return null;
  }

  const items = parseListItems(summary);
  const hasList = items.length > 0;

  return (
    <div className="rounded-xl border border-[color-mix(in_srgb,var(--success)_28%,transparent)] bg-[var(--success-soft)] p-4">
      <div className="mb-2 flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.14em] text-[var(--success)]">
        <CheckCircle2 className="h-3.5 w-3.5" />
        Summary
      </div>

      {hasList ? (
        <BulletList items={items} />
      ) : (
        <p className="text-sm leading-6 text-[var(--text)]">
          <InlineText text={summary} />
        </p>
      )}
    </div>
  );
}

function MultiTaskAnswer({ parsed }: { parsed: ParsedMultiTask }) {
  return (
    <div className="space-y-4">
      <MultiTaskIntro intro={parsed.intro} />

      <div className="space-y-3">
        {parsed.tasks.map((task) => (
          <MultiTaskCard key={task.index} task={task} />
        ))}
      </div>

      <MultiTaskSummary summary={parsed.summary} />
    </div>
  );
}

export function AssistantAnswerContent({
  answer,
  className,
}: AssistantAnswerContentProps) {
  const cleaned = stripTrailingSources(answer);

  if (isMultiTaskAnswer(cleaned)) {
    const parsed = parseMultiTaskAnswer(cleaned);

    if (parsed) {
      return (
        <div className={cn("assistant-answer", className)}>
          <MultiTaskAnswer parsed={parsed} />
        </div>
      );
    }
  }

  const structured = parseStructuredSections(cleaned);

  if (structured && structured.some((section) => section.title)) {
    return (
      <div className={cn("assistant-answer", className)}>
        <StructuredAnswer answer={cleaned} />
      </div>
    );
  }

  return (
    <div className={cn("assistant-answer", className)}>
      <ParagraphBlock text={cleaned} />
    </div>
  );
}
