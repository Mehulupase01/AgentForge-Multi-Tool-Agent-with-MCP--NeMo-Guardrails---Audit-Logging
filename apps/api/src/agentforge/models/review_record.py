from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task import Task


class ReviewTargetType(str, Enum):
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    LLM_OUTPUT = "llm_output"
    AGENT_RUN = "agent_run"


class ReviewVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class ReviewRecord(Base, TimestampMixin):
    __tablename__ = "review_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[ReviewTargetType] = mapped_column(
        SAEnum(ReviewTargetType, name="review_target_type"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(32), nullable=False, default="security_officer")
    verdict: Mapped[ReviewVerdict] = mapped_column(
        SAEnum(ReviewVerdict, name="review_verdict"),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    task: Mapped["Task"] = relationship(back_populates="review_records")

    __table_args__ = (
        Index("ix_review_records_task_id", "task_id"),
        Index("ix_review_records_target", "target_type", "target_id"),
        Index("ix_review_records_verdict", "verdict"),
    )
