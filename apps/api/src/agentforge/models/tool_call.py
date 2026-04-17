from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.approval import Approval
    from agentforge.models.task_step import TaskStep


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_step_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    server_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("approvals.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task_step: Mapped["TaskStep"] = relationship(back_populates="tool_calls")
    approval: Mapped["Approval | None"] = relationship(back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_calls_approval_id", "approval_id"),
        Index("ix_tool_calls_server_tool", "server_name", "tool_name"),
        Index("ix_tool_calls_task_step_id", "task_step_id"),
    )
