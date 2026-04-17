from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.llm_call import LLMCall
    from agentforge.models.task import Task
    from agentforge.models.tool_call import ToolCall


class StepType(str, Enum):
    LLM_REASONING = "llm_reasoning"
    TOOL_CALL = "tool_call"
    APPROVAL_GATE = "approval_gate"
    GUARDRAIL_BLOCK = "guardrail_block"
    USER_RESPONSE = "user_response"


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
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="task_step",
        cascade="all, delete-orphan",
    )
    llm_calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="task_step",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_task_steps_task_id_ordinal", "task_id", "ordinal", unique=True),
        Index("ix_task_steps_status", "status"),
    )
