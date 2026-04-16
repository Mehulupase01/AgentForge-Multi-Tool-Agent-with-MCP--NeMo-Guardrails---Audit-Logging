from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from agentforge.models.base import Base, new_uuid


class AuditEvent(Base):
    """Append-only. Application code must never update or delete these rows."""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_sequence", "sequence", unique=True),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_session_id", "session_id"),
        Index("ix_audit_events_task_id", "task_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )
