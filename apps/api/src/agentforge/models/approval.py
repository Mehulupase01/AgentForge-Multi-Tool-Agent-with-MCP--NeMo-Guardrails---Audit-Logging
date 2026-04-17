from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task import Task
    from agentforge.models.task_step import TaskStep
    from agentforge.models.tool_call import ToolCall


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_step_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=True,
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, name="risk_level"),
        nullable=False,
    )
    risk_reason: Mapped[str] = mapped_column(Text, nullable=False)
    action_summary: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[ApprovalDecision] = mapped_column(
        SAEnum(ApprovalDecision, name="approval_decision"),
        nullable=False,
        default=ApprovalDecision.PENDING,
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="approvals")
    task_step: Mapped["TaskStep | None"] = relationship(back_populates="approvals")
    tool_calls: Mapped[list["ToolCall"]] = relationship(back_populates="approval")

    __table_args__ = (
        Index("ix_approvals_task_id", "task_id"),
        Index("ix_approvals_decision", "decision"),
        Index("ix_approvals_requested_at", "requested_at"),
    )
