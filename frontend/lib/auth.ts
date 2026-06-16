// Account auth for AIRA-X (minimal, production-minded).
//
// Holds the signed account token in localStorage and exposes a tiny client:
// register / login / logout / me, plus `authHeaders()` so every owner-scoped
// request (chat, upload, preferences) carries the bearer token. When signed in,
// the backend scopes durable data to the account (cross-device); when signed
// out, it falls back to the session — an explicit, honest distinction.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "aira_auth_token";
const ACCOUNT_KEY = "aira_account";

export type Account = {
  id: string;
  email: string;
  display_name: string;
  workspace_id: string | null;
  owner_key: string;
  created_at: string | null;
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** Bearer header for a token, or an empty object — safe to spread into fetch. */
export function authHeaders(token: string | null | undefined): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function isAuthenticated(token: string | null | undefined): boolean {
  return typeof token === "string" && token.length > 0;
}

// ── Token + account storage ──────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function persist(token: string, account: Account): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(ACCOUNT_KEY, JSON.stringify(account));
  } catch {
    /* storage blocked — stay in-memory for this tab */
  }
}

export function getCachedAccount(): Account | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ACCOUNT_KEY);
    return raw ? (JSON.parse(raw) as Account) : null;
  } catch {
    return null;
  }
}

/** Headers for the current signed-in account (empty when signed out). */
export function currentAuthHeaders(): Record<string, string> {
  return authHeaders(getToken());
}

// ── API client ───────────────────────────────────────────────────────────────

async function authRequest(path: string, body: unknown): Promise<{ token: string; account: Account }> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data?.detail === "string" ? data.detail : "Authentication failed.");
  }
  persist(data.token, data.account);
  return data;
}

export function register(email: string, password: string, displayName?: string): Promise<{ token: string; account: Account }> {
  return authRequest("/auth/register", { email, password, display_name: displayName || null });
}

export function login(email: string, password: string): Promise<{ token: string; account: Account }> {
  return authRequest("/auth/login", { email, password });
}

export function logout(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(ACCOUNT_KEY);
  } catch {
    /* ignore */
  }
}

/** Validate the stored token against the backend; clears it if no longer valid. */
export async function fetchMe(): Promise<Account | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const res = await fetch(`${API_URL}/auth/me`, { headers: authHeaders(token), cache: "no-store" });
    if (!res.ok) {
      if (res.status === 401) logout();
      return null;
    }
    const data = await res.json();
    return (data?.account as Account) ?? null;
  } catch {
    return null;
  }
}
