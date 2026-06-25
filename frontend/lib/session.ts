// Stable, persisted client session id.
//
// With no login yet, the session id IS the ownership scope for memory,
// preferences, uploaded documents, and quotas. It must be stable across page
// reloads and across pages (chat ⇄ settings) so the preferences you edit in
// Settings are the ones the assistant applies in chat. We persist it in
// localStorage; a fresh random id is generated only the first time.

const STORAGE_KEY = "aira_session_id";

function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `s_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

/** Get (or lazily create + persist) the stable session id for this browser. */
export function getSessionId(): string {
  if (typeof window === "undefined") return "default"; // SSR: never persists
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && existing.trim()) return existing;
    const fresh = randomId();
    window.localStorage.setItem(STORAGE_KEY, fresh);
    return fresh;
  } catch {
    // localStorage blocked (private mode) — fall back to an in-memory id.
    return randomId();
  }
}
