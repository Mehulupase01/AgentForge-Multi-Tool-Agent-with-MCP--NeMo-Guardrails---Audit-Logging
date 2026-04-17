from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.models.base import Base, new_uuid


class RedteamCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFIL = "data_exfil"
    PII_LEAK = "pii_leak"
    JAILBREAK = "jailbreak"
    TOOL_ABUSE = "tool_abuse"
    GOAL_HIJACK = "goal_hijack"


class RedteamOutcome(str, Enum):
    BLOCKED = "blocked"
    ALLOWED_SAFE = "allowed_safe"
    ALLOWED_UNSAFE = "allowed_unsafe"


class RedteamRun(Base):
    __tablename__ = "redteam_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_scenarios: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_compliance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    results: Mapped[list["RedteamResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RedteamResult(Base):
    __tablename__ = "redteam_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("redteam_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[RedteamCategory] = mapped_column(
        SAEnum(RedteamCategory, name="redteam_category"),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_outcome: Mapped[RedteamOutcome] = mapped_column(
        SAEnum(RedteamOutcome, name="redteam_outcome"),
        nullable=False,
    )
    actual_outcome: Mapped[RedteamOutcome] = mapped_column(
        SAEnum(RedteamOutcome, name="redteam_outcome"),
        nullable=False,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped["RedteamRun"] = relationship(back_populates="results")

    __table_args__ = (
        Index("ix_redteam_results_run_id", "run_id"),
        Index("ix_redteam_results_category_passed", "category", "passed"),
    )
