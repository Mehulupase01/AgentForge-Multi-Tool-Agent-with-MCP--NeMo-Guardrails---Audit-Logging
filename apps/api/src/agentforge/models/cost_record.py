from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.agent_run import AgentRole
from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.llm_call import LLMCall
    from agentforge.models.task import Task


class CostRecord(Base, TimestampMixin):
    __tablename__ = "cost_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_call_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("llm_calls.id", ondelete="CASCADE"),
        nullable=True,
    )
    agent_role: Mapped[AgentRole] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    usd_cost: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    task: Mapped["Task"] = relationship(back_populates="cost_records")
    llm_call: Mapped["LLMCall | None"] = relationship(back_populates="cost_record")

    __table_args__ = (
        Index("ix_cost_records_task_id", "task_id"),
        Index("ix_cost_records_agent_role", "agent_role"),
        Index("ix_cost_records_model", "model"),
    )
