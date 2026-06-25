// Active resource scope (foundation only).
//
// AIRA-X resources are owned by a scope: an account's "Personal" scope by
// default, or a workspace scope later. This module holds the *active* scope so
// owner-scoped requests can carry an `X-Workspace-Id` header — the backend only
// honours it for members and otherwise falls back to personal scope. No switcher
// UI yet: signed-in users are simply "Personal". The plumbing is here so adding
// workspace switching later is a localStorage write, not a refactor.

const ACTIVE_WORKSPACE_KEY = "aira_active_workspace";

export const PERSONAL_SCOPE_LABEL = "Personal";

/** Header for the active workspace, or empty (Personal) — safe to spread. */
export function workspaceHeaders(workspaceId: string | null | undefined): Record<string, string> {
  return workspaceId ? { "X-Workspace-Id": workspaceId } : {};
}

/** A calm label for the active scope (just "Personal" until workspaces ship). */
export function scopeLabel(workspaceName: string | null | undefined): string {
  return workspaceName && workspaceName.trim() ? workspaceName : PERSONAL_SCOPE_LABEL;
}

export function getActiveWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    return null;
  }
}

export function setActiveWorkspaceId(workspaceId: string | null): void {
  try {
    if (workspaceId) window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId);
    else window.localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    /* storage blocked — stay personal for this tab */
  }
}

/** Headers for the current active scope (empty when Personal). */
export function currentScopeHeaders(): Record<string, string> {
  return workspaceHeaders(getActiveWorkspaceId());
}
