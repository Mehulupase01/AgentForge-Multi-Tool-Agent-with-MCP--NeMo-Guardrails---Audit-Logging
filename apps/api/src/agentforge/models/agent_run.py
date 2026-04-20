from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task import Task
    from agentforge.models.task_step import TaskStep


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    ANALYST = "analyst"
    RESEARCHER = "researcher"
    ENGINEER = "engineer"
    SECRETARY = "secretary"
    SECURITY_OFFICER = "security_officer"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    HANDED_OFF = "handed_off"
    FAILED = "failed"
    REJECTED = "rejected"


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AgentRole] = mapped_column(
        SAEnum(AgentRole, name="agent_role"),
        nullable=False,
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    handoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        SAEnum(AgentRunStatus, name="agent_run_status"),
        nullable=False,
        default=AgentRunStatus.RUNNING,
    )
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="agent_runs")
    parent_run: Mapped["AgentRun | None"] = relationship(
        remote_side="AgentRun.id",
        back_populates="child_runs",
    )
    child_runs: Mapped[list["AgentRun"]] = relationship(back_populates="parent_run")
    task_steps: Mapped[list["TaskStep"]] = relationship(back_populates="agent_run")

    __table_args__ = (
        Index("ix_agent_runs_task_id", "task_id"),
        Index("ix_agent_runs_role_status", "role", "status"),
    )
