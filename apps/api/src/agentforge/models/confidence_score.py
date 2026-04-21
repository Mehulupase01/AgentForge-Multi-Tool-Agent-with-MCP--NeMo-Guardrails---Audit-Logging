from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Index, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task import Task


class ConfidenceScope(str, Enum):
    TASK = "task"
    STEP = "step"
    AGENT_RUN = "agent_run"


class ConfidenceScore(Base, TimestampMixin):
    __tablename__ = "confidence_scores"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[ConfidenceScope] = mapped_column(
        SAEnum(ConfidenceScope, name="confidence_scope"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    heuristic_value: Mapped[float] = mapped_column(Float, nullable=False)
    self_reported_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    factors_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    task: Mapped["Task"] = relationship(back_populates="confidence_scores")

    __table_args__ = (
        Index("ix_confidence_scores_task_id", "task_id"),
        Index("ix_confidence_scores_target", "scope", "target_id"),
    )
