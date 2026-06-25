# File: backend/app/authz.py
"""
Authorization policy — the single, small place that turns a scope + a role into
an access decision.

A clean foundation, not an enterprise RBAC product:

  Roles   (workspace): viewer < editor < owner
  Perms   : view (read) < edit (mutate content) < manage (change settings)

  viewer -> {view}
  editor -> {view, edit}
  owner  -> {view, edit, manage}

Safe by default: a workspace member with no/unknown role gets nothing. Personal
scope (account/session) is full self-access — a person owns their own data, so
none of this complicates single-user use. The supervisor and routes ask
`can(scope, PERM_*)` and get a clear, user-safe `AccessDecision`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# ── Workspace roles (small, ranked) ──────────────────────────────────────────
ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

WORKSPACE_ROLES = (ROLE_VIEWER, ROLE_EDITOR, ROLE_OWNER)
_ROLE_RANK = {ROLE_VIEWER: 1, ROLE_EDITOR: 2, ROLE_OWNER: 3}

# ── Permissions ──────────────────────────────────────────────────────────────
PERM_VIEW = "view"      # read shared resources (docs, prefs, downloads)
PERM_EDIT = "edit"      # mutate content (upload docs, generate artifacts, run flows)
PERM_MANAGE = "manage"  # change workspace settings/defaults (and, later, members)

_ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_VIEWER: {PERM_VIEW},
    ROLE_EDITOR: {PERM_VIEW, PERM_EDIT},
    ROLE_OWNER: {PERM_VIEW, PERM_EDIT, PERM_MANAGE},
}

_DENY_MESSAGES = {
    PERM_EDIT: "You have view-only access to this workspace — ask an editor or owner to make this change.",
    PERM_MANAGE: "Only a workspace owner can change workspace settings.",
    PERM_VIEW: "You don't have access to this workspace resource.",
}


def normalize_role(role: Optional[str]) -> Optional[str]:
    """Map a stored role to a known role; unknown/legacy -> safe viewer."""
    if role in _ROLE_PERMISSIONS:
        return role
    if role == "member":  # legacy default before roles existed
        return ROLE_VIEWER
    return None


def role_rank(role: Optional[str]) -> int:
    return _ROLE_RANK.get(normalize_role(role) or "", 0)


def role_can(role: Optional[str], permission: str) -> bool:
    return permission in _ROLE_PERMISSIONS.get(normalize_role(role) or "", set())


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    permission: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def can(scope: Any, permission: str) -> AccessDecision:
    """Decide whether the active scope may perform a permission-gated action.

    Personal/account/session scope is full self-access. Workspace scope is gated
    by the member's role; an unknown/absent role is denied (safe default).
    """
    if scope is None or not getattr(scope, "is_workspace", False):
        return AccessDecision(True, permission, "personal scope")
    role = getattr(scope, "role", None)
    if role_can(role, permission):
        return AccessDecision(True, permission, f"role:{normalize_role(role)}")
    return AccessDecision(False, permission, _DENY_MESSAGES.get(permission, "Insufficient workspace permission."))
