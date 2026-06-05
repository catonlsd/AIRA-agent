export type MultiTaskItem = {
  index: number;
  title: string;
  body: string;
};

export type ParsedMultiTask = {
  intro: string;
  tasks: MultiTaskItem[];
  summary: string;
};

export type AnswerSection = {
  title: string;
  content: string;
  variant: "default" | "code" | "output" | "meta";
};

const CODE_SECTION_TITLES = new Set([
  "code",
  "command",
  "path",
]);

const OUTPUT_SECTION_TITLES = new Set([
  "output",
  "outputs",
  "error output",
]);

const META_SECTION_TITLES = new Set([
  "tool used",
  "execution status",
  "run id",
  "previous final answer",
]);

const LIST_SECTION_TITLES = new Set([
  "execution summary",
  "summary",
]);

const KNOWN_SECTION_TITLES = new Set([
  ...CODE_SECTION_TITLES,
  ...OUTPUT_SECTION_TITLES,
  ...META_SECTION_TITLES,
  ...LIST_SECTION_TITLES,
  "tool used",
  "execution status",
  "previous final answer",
]);

export function isKnownSectionTitle(title: string): boolean {
  return KNOWN_SECTION_TITLES.has(title.trim().toLowerCase());
}

const SECTION_LINE = /^([A-Za-z][A-Za-z0-9\s]*):\s*([\s\S]*)?$/;

// ─── Markdown normalisation ───────────────────────────────────────────────────
// The backend can return raw markdown (##, **, *, -, numbered lists).
// We convert it to plain structured text so the existing renderer handles it
// correctly without ever showing raw syntax to the user.

/**
 * Convert markdown heading lines to plain title-cased text.
 *   ## Life Sciences Explanation  →  Life Sciences Explanation
 *   ### Overview                  →  Overview
 */
function stripMarkdownHeadings(text: string): string {
  return text.replace(/^#{1,6}\s+(.+)$/gm, "$1");
}

/**
 * Convert **bold** and *italic* markers to plain text.
 * The InlineText component in assistant-answer.tsx handles **bold** itself,
 * so we only need to strip *italic* (single asterisk/underscore) here.
 */
function stripMarkdownEmphasis(text: string): string {
  // Remove italic: *word* or _word_ but leave **bold** intact for InlineText
  return text
    .replace(/(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)/g, "$1")
    .replace(/(?<!_)_(?!_)([^_]+)(?<!_)_(?!_)/g, "$1");
}

/**
 * Convert markdown numbered lists to plain hyphen lists so parseListItems works.
 *   1. Item one  →  - Item one
 *   2. Item two  →  - Item two
 */
function normaliseNumberedLists(text: string): string {
  return text.replace(/^\d+\.\s+/gm, "- ");
}

/**
 * Master normaliser — run all markdown cleanup before any parsing.
 */
export function normaliseMarkdown(text: string): string {
  let out = text;
  out = stripMarkdownHeadings(out);
  out = stripMarkdownEmphasis(out);
  out = normaliseNumberedLists(out);
  // Collapse 3+ blank lines to 2 so paragraph splitting stays clean
  out = out.replace(/\n{3,}/g, "\n\n");
  return out;
}

// ─── Existing helpers (unchanged) ────────────────────────────────────────────

export function stripTrailingSources(answer: string): string {
  return answer
    .replace(/^\s*(Sources|Source|References|Reference)\s*:?\s*[\s\S]*$/im, "")
    .trim();
}

export function isMultiTaskAnswer(answer: string): boolean {
  return /^Task\s+\d+:/m.test(answer);
}

export function parseMultiTaskAnswer(answer: string): ParsedMultiTask | null {
  const cleaned = stripTrailingSources(answer);
  const matches = [...cleaned.matchAll(/^Task\s+(\d+):\s*(.*)$/gm)];

  if (matches.length < 2) {
    return null;
  }

  const introEnd = matches[0].index ?? 0;
  const intro = cleaned.slice(0, introEnd).trim();

  const tasks: MultiTaskItem[] = [];

  for (let i = 0; i < matches.length; i += 1) {
    const match = matches[i];
    const next = matches[i + 1];
    const bodyStart = (match.index ?? 0) + match[0].length;
    const bodyEnd = next?.index ?? cleaned.length;
    const body = cleaned.slice(bodyStart, bodyEnd).trim();

    tasks.push({
      index: Number(match[1]),
      title: match[2].trim() || `Task ${match[1]}`,
      body,
    });
  }

  const lastTask = tasks[tasks.length - 1];
  const summaryMarker = lastTask.body.search(/\n\s*Summary:\s*\n/i);

  if (summaryMarker >= 0) {
    const summary = lastTask.body
      .slice(summaryMarker)
      .replace(/^Summary:\s*/i, "")
      .trim();
    lastTask.body = lastTask.body.slice(0, summaryMarker).trim();
    return { intro, tasks, summary };
  }

  const trailingSummary = cleaned.match(/\n\s*Summary:\s*\n([\s\S]*)$/i);
  if (trailingSummary) {
    const summary = trailingSummary[1].trim();
    const last = tasks[tasks.length - 1];
    last.body = last.body.replace(trailingSummary[0], "").trim();
    return { intro, tasks, summary };
  }

  return { intro, tasks, summary: "" };
}

export function getSectionVariant(title: string): AnswerSection["variant"] {
  const key = title.trim().toLowerCase();

  if (CODE_SECTION_TITLES.has(key)) return "code";
  if (OUTPUT_SECTION_TITLES.has(key)) return "output";
  if (META_SECTION_TITLES.has(key)) return "meta";

  return "default";
}

export function sectionUsesList(title: string, content: string): boolean {
  const key = title.trim().toLowerCase();

  if (LIST_SECTION_TITLES.has(key)) return true;

  if (key === "execution status") {
    return content.trim().startsWith("-");
  }

  return (
    /^-\s+/m.test(content) &&
    content.split("\n").every((line) => {
      const trimmed = line.trim();
      return !trimmed || trimmed.startsWith("-");
    })
  );
}

export function parseListItems(content: string): string[] {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("-"))
    .map((line) => line.replace(/^-\s*/, "").trim())
    .filter(Boolean)
    .filter((item) => !isTechnicalListItem(item));
}

export function isTechnicalListItem(item: string): boolean {
  const normalized = item.trim().toLowerCase();
  return (
    normalized.startsWith("run id:") ||
    normalized.startsWith("decision:") ||
    normalized.startsWith("tool_action:") ||
    normalized.startsWith("agent_name:") ||
    normalized.startsWith("agent:")
  );
}

export function partitionAnswerSections(sections: AnswerSection[]): {
  visible: AnswerSection[];
  technical: AnswerSection[];
} {
  const visible: AnswerSection[] = [];
  const technical: AnswerSection[] = [];

  for (const section of sections) {
    if (!section.title) {
      visible.push(section);
      continue;
    }

    if (section.variant === "meta") {
      technical.push(section);
      continue;
    }

    visible.push(section);
  }

  return { visible, technical };
}

export function parseStructuredSections(
  answer: string
): AnswerSection[] | null {
  const cleaned = stripTrailingSources(answer);
  const lines = cleaned.split("\n");

  if (lines.length < 2) return null;

  const sections: AnswerSection[] = [];
  let buffer: string[] = [];
  let currentTitle: string | null = null;

  function flushSection() {
    if (!currentTitle) return;
    const content = buffer.join("\n").trim();
    buffer = [];
    if (content) {
      sections.push({
        title: currentTitle,
        content,
        variant: getSectionVariant(currentTitle),
      });
    }
  }

  function flushPreamble() {
    const preamble = buffer.join("\n").trim();
    buffer = [];
    if (preamble) {
      sections.push({ title: "", content: preamble, variant: "default" });
    }
  }

  for (const line of lines) {
    const sectionMatch = line.match(SECTION_LINE);

    if (
      sectionMatch &&
      sectionMatch[1].length <= 40 &&
      !line.startsWith("-")
    ) {
      const title = sectionMatch[1].trim();
      const inlineContent = sectionMatch[2]?.trim() ?? "";

      if (currentTitle) {
        flushSection();
      } else if (buffer.length > 0) {
        flushPreamble();
      }

      currentTitle = title;
      buffer = inlineContent ? [inlineContent] : [];
      continue;
    }

    buffer.push(line);
  }

  if (currentTitle) {
    flushSection();
  } else if (buffer.length > 0) {
    flushPreamble();
  }

  const knownSections = sections.filter(
    (s) => s.title && isKnownSectionTitle(s.title)
  );

  if (knownSections.length === 0) return null;

  return sections;
}

export function splitParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function formatInlineText(text: string): string {
  return text.trim();
}