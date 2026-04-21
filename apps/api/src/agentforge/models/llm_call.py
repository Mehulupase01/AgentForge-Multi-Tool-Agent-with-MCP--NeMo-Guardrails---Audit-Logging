from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.cost_record import CostRecord
    from agentforge.models.task_step import TaskStep


class LLMCall(Base, TimestampMixin):
    __tablename__ = "llm_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_step_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    completion: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_rails_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_rails_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    task_step: Mapped["TaskStep | None"] = relationship(back_populates="llm_calls")
    cost_record: Mapped["CostRecord | None"] = relationship(
        back_populates="llm_call",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_llm_calls_task_step_id", "task_step_id"),
        Index("ix_llm_calls_blocked", "blocked"),
    )
