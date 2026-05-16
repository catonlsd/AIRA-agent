const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Citation = {
  source_type: string;
  title: string;
  url?: string | null;
  document_id?: number | null;
  chunk_id?: number | null;
  page?: number | null;
  snippet?: string | null;
};

export type ChatResponse = {
  answer: string;
  citations: Citation[];
  confidence: string;
  plan: {
    rewritten_query: string;
    needs_documents: boolean;
    needs_web: boolean;
    reason: string;
  };
};

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendChat(question: string, useWeb?: boolean): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, use_web: useWeb })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadDocuments(files: FileList): Promise<{ documents: unknown[] }> {
  const body = new FormData();
  Array.from(files).forEach((file) => body.append("files", file));
  const res = await fetch(`${API_URL}/upload`, { method: "POST", body });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function summarizeDocument(documentId: number): Promise<{ summary: string; citations: Citation[] }> {
  const res = await fetch(`${API_URL}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function runAiraX(goal: string) {
  const response = await fetch(`${API_URL}/aira-x/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ goal }),
  });

  if (!response.ok) {
    throw new Error("Failed to run AIRA-X workflow");
  }

  return response.json();
}

export async function getAiraXTools() {
  const response = await fetch(`${API_URL}/aira-x/tools`);

  if (!response.ok) {
    throw new Error("Failed to fetch AIRA-X tools");
  }

  return response.json();
}
