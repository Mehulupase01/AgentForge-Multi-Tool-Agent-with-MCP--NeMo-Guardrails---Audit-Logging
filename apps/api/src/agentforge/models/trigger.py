from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task import Task


class TriggerSource(str, Enum):
    GITHUB_WEBHOOK = "github_webhook"
    GENERIC_WEBHOOK = "generic_webhook"
    SCHEDULE = "schedule"


class TriggerStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class TriggerEventStatus(str, Enum):
    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROCESSED = "processed"
    FAILED = "failed"


class Trigger(Base, TimestampMixin):
    __tablename__ = "triggers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[TriggerSource] = mapped_column(
        SAEnum(TriggerSource, name="trigger_source"),
        nullable=False,
    )
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TriggerStatus] = mapped_column(
        SAEnum(TriggerStatus, name="trigger_status"),
        nullable=False,
        default=TriggerStatus.ENABLED,
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["TriggerEvent"]] = relationship(
        back_populates="trigger",
        cascade="all, delete-orphan",
        order_by="TriggerEvent.received_at",
    )


class TriggerEvent(Base, TimestampMixin):
    __tablename__ = "trigger_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    trigger_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("triggers.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[TriggerEventStatus] = mapped_column(
        SAEnum(TriggerEventStatus, name="trigger_event_status"),
        nullable=False,
        default=TriggerEventStatus.RECEIVED,
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resulting_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tasks.id"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    trigger: Mapped["Trigger"] = relationship(back_populates="events")
    resulting_task: Mapped["Task | None"] = relationship()

    __table_args__ = (
        Index("ix_trigger_events_trigger_id", "trigger_id"),
        Index("ix_trigger_events_status", "status"),
    )
