from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.agent_run import AgentRun
    from agentforge.models.approval import Approval
    from agentforge.models.session import Session
    from agentforge.models.task_step import TaskStep


class TaskStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    session_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status"),
        nullable=False,
        default=TaskStatus.PLANNING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    session: Mapped["Session"] = relationship(back_populates="tasks")
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="AgentRun.started_at",
    )
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStep.ordinal",
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Approval.requested_at",
    )

    __table_args__ = (
        Index("ix_tasks_session_id", "session_id"),
        Index("ix_tasks_status", "status"),
    )
