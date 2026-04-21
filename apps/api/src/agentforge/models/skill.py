from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, TimestampMixin, new_uuid

if TYPE_CHECKING:
    from agentforge.models.task_step import TaskStep


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False)
    tools_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    knowledge_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    invocations: Mapped[list["SkillInvocation"]] = relationship(back_populates="skill")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_skills_name_version"),
        Index("ix_skills_agent_role", "agent_role"),
    )


class SkillInvocation(Base, TimestampMixin):
    __tablename__ = "skill_invocations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    skill_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("skills.id"),
        nullable=False,
    )
    task_step_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_checks_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    injected_knowledge_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    skill: Mapped["Skill"] = relationship(back_populates="invocations")
    task_step: Mapped["TaskStep"] = relationship(back_populates="skill_invocations")

    __table_args__ = (
        Index("ix_skill_invocations_skill_id", "skill_id"),
        Index("ix_skill_invocations_task_step_id", "task_step_id"),
    )
