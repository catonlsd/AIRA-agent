// Workspaces + membership client, and the active-scope helpers that make
// switching real (every owner-scoped request already carries the active
// workspace header — see lib/scope.ts). Minimal collaboration loop: list/create
// workspaces, list/add/update/remove members. No owner keys ever surface here.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Self-contained bearer header (kept inline so this module stays dependency-free
// for unit tests). Mirrors lib/auth's token key. Member-management endpoints take
// the workspace id in the path, so no scope header is needed here.
function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = window.localStorage.getItem("aira_auth_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export type Workspace = {
  id: string;
  name: string;
  owner_account_id: string;
  role?: string; // the current account's role in this workspace
  created_at: string | null;
};

export type Member = {
  account_id: string;
  email: string;
  display_name: string;
  role: string;
};

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

export const PERSONAL = { id: "", name: "Personal" } as const;

/** Can the given role manage members / shared defaults? (owner only) */
export function canManage(role: string | null | undefined): boolean {
  return role === "owner";
}

/** Can the given role edit shared content? (editor or owner) */
export function canEdit(role: string | null | undefined): boolean {
  return role === "owner" || role === "editor";
}

/** Human role label. */
export function roleLabel(role: string | null | undefined): string {
  if (role === "owner") return "Owner";
  if (role === "editor") return "Editor";
  if (role === "viewer") return "Viewer";
  return "Member";
}

/** The active workspace from a list, or null when Personal / stale selection. */
export function activeWorkspace(workspaces: Workspace[], activeId: string | null): Workspace | null {
  if (!activeId) return null;
  return workspaces.find((w) => w.id === activeId) ?? null;
}

/** Drop any active selection that is no longer a workspace the user belongs to
 *  (e.g. removed) — returns the safe active id (falls back to Personal). */
export function reconcileActiveId(workspaces: Workspace[], activeId: string | null): string {
  if (activeId && workspaces.some((w) => w.id === activeId)) return activeId;
  return "";
}

// ── API client ───────────────────────────────────────────────────────────────

function headers(json = false): Record<string, string> {
  return { ...(json ? { "Content-Type": "application/json" } : {}), ...authHeader() };
}

async function asJson<T>(res: Response, pick: (b: any) => T): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return pick(body);
}

export async function listWorkspaces(): Promise<Workspace[]> {
  return asJson(await fetch(`${API_URL}/workspaces`, { headers: headers(), cache: "no-store" }), (b) => b.workspaces ?? []);
}

export async function createWorkspace(name: string): Promise<Workspace> {
  return asJson(
    await fetch(`${API_URL}/workspaces`, { method: "POST", headers: headers(true), body: JSON.stringify({ name }) }),
    (b) => b.workspace
  );
}

export async function listMembers(workspaceId: string): Promise<Member[]> {
  return asJson(await fetch(`${API_URL}/workspaces/${workspaceId}/members`, { headers: headers(), cache: "no-store" }), (b) => b.members ?? []);
}

export async function addMember(workspaceId: string, email: string, role: string): Promise<Member[]> {
  return asJson(
    await fetch(`${API_URL}/workspaces/${workspaceId}/members`, { method: "POST", headers: headers(true), body: JSON.stringify({ email, role }) }),
    (b) => b.members ?? []
  );
}

export async function updateMemberRole(workspaceId: string, accountId: string, role: string): Promise<Member[]> {
  return asJson(
    await fetch(`${API_URL}/workspaces/${workspaceId}/members/${accountId}`, { method: "PATCH", headers: headers(true), body: JSON.stringify({ role }) }),
    (b) => b.members ?? []
  );
}

export async function removeMember(workspaceId: string, accountId: string): Promise<Member[]> {
  return asJson(
    await fetch(`${API_URL}/workspaces/${workspaceId}/members/${accountId}`, { method: "DELETE", headers: headers() }),
    (b) => b.members ?? []
  );
}
