import json

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ConversationMessage, UserPreference


class MemoryService:
    def recent_history(self, db: Session, limit: int | None = None) -> list[dict]:
        rows = (
            db.query(ConversationMessage)
            .order_by(desc(ConversationMessage.created_at))
            .limit(limit or settings.memory_limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "citations": json.loads(row.citations_json or "[]"),
                "created_at": row.created_at.isoformat(),
            }
            for row in reversed(rows)
        ]

    def add_message(self, db: Session, role: str, content: str, citations: list[dict] | None = None) -> None:
        db.add(
            ConversationMessage(
                role=role,
                content=content,
                citations_json=json.dumps(citations or []),
            )
        )
        db.commit()

    def clear_history(self, db: Session) -> None:
        db.query(ConversationMessage).delete()
        db.commit()

    def preferences(self, db: Session) -> dict:
        rows = db.query(UserPreference).filter(UserPreference.is_sensitive.is_(False)).all()
        return {row.key: row.value for row in rows}

    def remember_preference(self, db: Session, key: str, value: str, is_sensitive: bool = False) -> None:
        existing = db.query(UserPreference).filter(UserPreference.key == key).first()
        if existing:
            existing.value = value
            existing.is_sensitive = is_sensitive
        else:
            db.add(UserPreference(key=key, value=value, is_sensitive=is_sensitive))
        db.commit()
