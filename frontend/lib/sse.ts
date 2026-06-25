// File: frontend/lib/sse.ts
// Pure, dependency-free Server-Sent Events parsing helpers.
// Kept separate from network code so the parsing logic is easy to reason about
// and unit-test (the project has no test runner yet; these are pure functions).

export type SSEEvent = {
  type: string;
  data: unknown;
};

/**
 * Parse one SSE block (the text between blank-line separators) into an event.
 * Returns null for blocks with no `data:` line (e.g. comments/heartbeats).
 */
export function parseSSEBlock(block: string): SSEEvent | null {
  let type = "message";
  const dataLines: string[] = [];

  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith("event:")) {
      type = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (dataLines.length === 0) return null;

  const raw = dataLines.join("\n");
  let data: unknown = raw;
  try {
    data = JSON.parse(raw);
  } catch {
    // Leave as raw string if it is not JSON.
  }
  return { type, data };
}

/**
 * Split a streaming buffer into complete SSE blocks plus any trailing partial.
 * Feed `rest` back in with the next chunk.
 */
export function splitSSEBuffer(buffer: string): { blocks: string[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const blocks = parts.map((p) => p.trim()).filter(Boolean);
  return { blocks, rest };
}
