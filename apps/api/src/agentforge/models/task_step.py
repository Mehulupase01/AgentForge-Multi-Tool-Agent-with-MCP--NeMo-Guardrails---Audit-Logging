from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.agent_run import AgentRole
from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.agent_run import AgentRun
    from agentforge.models.approval import Approval
    from agentforge.models.llm_call import LLMCall
    from agentforge.models.skill import SkillInvocation
    from agentforge.models.task import Task
    from agentforge.models.tool_call import ToolCall


class StepType(str, Enum):
    LLM_REASONING = "llm_reasoning"
    TOOL_CALL = "tool_call"
    APPROVAL_GATE = "approval_gate"
    GUARDRAIL_BLOCK = "guardrail_block"
    USER_RESPONSE = "user_response"
    REFLECTION = "reflection"
    RETRY = "retry"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStep(Base, TimestampMixin):
    __tablename__ = "task_steps"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[StepType] = mapped_column(
        SAEnum(StepType, name="step_type"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[StepStatus] = mapped_column(
        SAEnum(StepStatus, name="step_status"),
        nullable=False,
        default=StepStatus.PENDING,
    )
    agent_role: Mapped[AgentRole] = mapped_column(
        SAEnum(AgentRole, name="agent_role"),
        nullable=False,
        default=AgentRole.ORCHESTRATOR,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_step_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")
    parent_step: Mapped["TaskStep | None"] = relationship(
        remote_side="TaskStep.id",
        back_populates="retry_steps",
    )
    retry_steps: Mapped[list["TaskStep"]] = relationship(back_populates="parent_step")
    agent_run: Mapped["AgentRun | None"] = relationship(back_populates="task_steps")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="task_step",
        cascade="all, delete-orphan",
    )
    llm_calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="task_step",
        cascade="all, delete-orphan",
    )
    skill_invocations: Mapped[list["SkillInvocation"]] = relationship(
        back_populates="task_step",
        cascade="all, delete-orphan",
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="task_step")

    __table_args__ = (
        Index("ix_task_steps_task_id_ordinal", "task_id", "ordinal", unique=True),
        Index("ix_task_steps_status", "status"),
        Index("ix_task_steps_agent_run_id", "agent_run_id"),
    )
