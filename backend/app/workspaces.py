# File: backend/app/workspaces.py
"""
Workspace service — the foundation for shared, scope-owned resources.

A workspace is a durable scope that can own resources (owner key
`workspace:<id>`) alongside personal accounts (`account:<id>`). This module is
the access-check home: it answers "is this account a member of this workspace?"
so scope resolution can safely grant workspace scope without leaking across
teams. Membership is a real table, so adding invited members/roles later is a
row insert — not a schema change or a call-site rewrite.

Deliberately minimal: create a workspace, list mine, check membership. No
invitations, no admin console, no RBAC matrix yet — those layer on top of this
without changing the shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.authz import ROLE_OWNER, ROLE_VIEWER, normalize_role
from app.db.database import Base, SessionLocal, engine
from app.db.models import Workspace, WorkspaceMember


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def workspace_owner_key(workspace_id: str) -> str:
    """The durable owner scope for a workspace (distinct from an account)."""
    return f"workspace:{workspace_id}"


class WorkspaceService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            Workspace.__table__.create(bind=engine, checkfirst=True)
            WorkspaceMember.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)

    # ── create / read ────────────────────────────────────────────────────────

    def create(self, owner_account_id: str, name: str) -> dict:
        name = (name or "").strip() or "Workspace"
        workspace_id = uuid4().hex
        with self._session_factory() as session:
            session.add(
                Workspace(
                    id=workspace_id,
                    name=name,
                    owner_account_id=owner_account_id,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
            # The creator is a member (owner role) from the start.
            session.add(
                WorkspaceMember(
                    id=uuid4().hex,
                    workspace_id=workspace_id,
                    account_id=owner_account_id,
                    role=ROLE_OWNER,
                    created_at=_now(),
                )
            )
            session.commit()
        return self.get(workspace_id) or {}

    def get(self, workspace_id: str) -> Optional[dict]:
        if not workspace_id:
            return None
        with self._session_factory() as session:
            ws = session.query(Workspace).filter(Workspace.id == workspace_id).first()
            return self._public(ws) if ws else None

    def list_for_account(self, account_id: str) -> list[dict]:
        if not account_id:
            return []
        with self._session_factory() as session:
            rows = (
                session.query(Workspace)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .filter(WorkspaceMember.account_id == account_id)
                .order_by(Workspace.created_at)
                .all()
            )
            return [self._public(ws) for ws in rows]

    # ── access checks ────────────────────────────────────────────────────────

    def _member_row(self, session, workspace_id: str, account_id: str) -> Optional[WorkspaceMember]:
        if not workspace_id or not account_id:
            return None
        return (
            session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.account_id == account_id,
            )
            .first()
        )

    def is_member(self, workspace_id: str, account_id: str) -> bool:
        with self._session_factory() as session:
            return self._member_row(session, workspace_id, account_id) is not None

    def get_role(self, workspace_id: str, account_id: str) -> Optional[str]:
        """The account's role in the workspace (normalized), or None if not a member."""
        with self._session_factory() as session:
            row = self._member_row(session, workspace_id, account_id)
            return normalize_role(row.role) if row else None

    def membership(self, workspace_id: str, account_id: str) -> Optional[dict]:
        """The workspace + the account's role, iff a member (one lookup)."""
        with self._session_factory() as session:
            row = self._member_row(session, workspace_id, account_id)
            if row is None:
                return None
            ws = session.query(Workspace).filter(Workspace.id == workspace_id).first()
            if ws is None:
                return None
            return {**self._public(ws), "role": normalize_role(row.role)}

    def get_if_member(self, workspace_id: str, account_id: str) -> Optional[dict]:
        """The workspace (with the caller's role) iff a member, else None."""
        return self.membership(workspace_id, account_id)

    def add_member(self, workspace_id: str, account_id: str, role: str = ROLE_VIEWER) -> Optional[dict]:
        """Add or update a member with a role (safe default: viewer). Foundation
        for a future invitation flow — durable role on the membership record."""
        role = normalize_role(role) or ROLE_VIEWER
        with self._session_factory() as session:
            existing = self._member_row(session, workspace_id, account_id)
            if existing:
                existing.role = role
            else:
                session.add(
                    WorkspaceMember(
                        id=uuid4().hex,
                        workspace_id=workspace_id,
                        account_id=account_id,
                        role=role,
                        created_at=_now(),
                    )
                )
            session.commit()
        return self.membership(workspace_id, account_id)

    def member_workspace_ids(self, account_id: str) -> list[str]:
        if not account_id:
            return []
        with self._session_factory() as session:
            rows = (
                session.query(WorkspaceMember.workspace_id)
                .filter(WorkspaceMember.account_id == account_id)
                .all()
            )
            return [row[0] for row in rows]

    # ── public view ──────────────────────────────────────────────────────────

    @staticmethod
    def _public(ws: Workspace) -> dict:
        return {
            "id": ws.id,
            "name": ws.name,
            "owner_account_id": ws.owner_account_id,
            "owner_key": workspace_owner_key(ws.id),
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        }


workspace_service = WorkspaceService()
