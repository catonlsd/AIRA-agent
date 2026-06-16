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

from app.db.database import Base, SessionLocal, engine
from app.db.models import Workspace, WorkspaceMember

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"


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

    def is_member(self, workspace_id: str, account_id: str) -> bool:
        if not workspace_id or not account_id:
            return False
        with self._session_factory() as session:
            return (
                session.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.account_id == account_id,
                )
                .first()
                is not None
            )

    def get_if_member(self, workspace_id: str, account_id: str) -> Optional[dict]:
        """The workspace iff the account is a member, else None (no leakage)."""
        if not self.is_member(workspace_id, account_id):
            return None
        return self.get(workspace_id)

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
