from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_columns() -> None:
    """Self-healing, additive column migrations for SQLite databases that were
    created before a column was introduced. Best-effort; never raises.

    `create_all` creates missing tables but won't ALTER an existing one, so a
    column added later (e.g. `documents.owner`) needs this. Each addition is
    nullable and idempotent."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        additions = {
            "documents": [("owner", "VARCHAR(128)")],
            "execution_jobs": [
                ("parent_job_id", "VARCHAR(36)"),
                ("origin", "VARCHAR(16)"),
                ("exec_class", "VARCHAR(24)"),
                ("priority", "INTEGER DEFAULT 0"),
            ],
            "webhook_deliveries": [
                ("redrive_of", "VARCHAR(36)"),
            ],
            "webhook_destinations": [
                ("alert_filter", "VARCHAR(255)"),
                ("origin_filter", "VARCHAR(64)"),
                ("suppress_seconds", "INTEGER"),
                ("escalate_after", "INTEGER"),
                ("stat_routed", "INTEGER DEFAULT 0"),
                ("stat_suppressed", "INTEGER DEFAULT 0"),
                ("stat_skipped", "INTEGER DEFAULT 0"),
                ("max_attempts", "INTEGER"),
                ("consecutive_failures", "INTEGER DEFAULT 0"),
                ("cooldown_until", "DATETIME"),
            ],
            "operator_incidents": [
                ("assignee", "VARCHAR(80)"),
                ("assigned_at", "DATETIME"),
            ],
            "incident_sync_records": [
                ("external_url", "VARCHAR(500)"),
            ],
            "incident_external_links": [
                ("last_checked_at", "DATETIME"),
                ("external_status", "VARCHAR(24)"),
                ("external_exists", "BOOLEAN"),
                ("detached_at", "DATETIME"),
                ("external_assignee", "VARCHAR(120)"),
                ("external_severity", "VARCHAR(24)"),
                ("external_updated_at", "VARCHAR(40)"),
                ("external_comment_count", "INTEGER"),
            ],
            "external_incident_targets": [
                ("profile", "VARCHAR(40)"),
                ("allow_apply_resolved", "BOOLEAN"),
                ("allow_apply_missing", "BOOLEAN"),
                ("allow_external_resolve", "BOOLEAN"),
                ("allow_external_reopen", "BOOLEAN"),
                ("allow_external_acknowledge", "BOOLEAN"),
                ("allow_push_outward", "BOOLEAN"),
                ("allow_external_assignee", "BOOLEAN"),
                ("allow_external_severity", "BOOLEAN"),
                ("allow_external_updated_at", "BOOLEAN"),
                ("allow_external_comment_count", "BOOLEAN"),
                ("allow_external_suggestions", "BOOLEAN"),
                ("last_validated_at", "DATETIME"),
                ("last_test_at", "DATETIME"),
                ("last_success_at", "DATETIME"),
                ("last_failure_at", "DATETIME"),
                ("last_check_error", "VARCHAR(200)"),
                ("last_check_kind", "VARCHAR(24)"),
            ],
        }
        for table, columns in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    except Exception:
        pass


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()
