from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.config import settings
from agentforge.models.approval import RiskLevel
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.schemas.task import PlanStep
from agentforge.services.approval_service import ApprovalService, RiskAssessment
from agentforge.services.audit_service import AuditService


class ReplayConflictError(RuntimeError):
    pass


@dataclass(slots=True)
class ReplayResult:
    task_id: UUID
    status: TaskStatus
    skipped_completed_steps: int = 0
    approval_id: UUID | None = None


class ReplayService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        approval_service: ApprovalService,
        audit_service: AuditService | None = None,
        max_checkpoint_age_hours: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._approval_service = approval_service
        self._audit_service = audit_service or AuditService()
        self._max_checkpoint_age_hours = max_checkpoint_age_hours or settings.replay_max_checkpoint_age_hours

    @staticmethod
    def derive_idempotency_key(
        *,
        task_id: UUID,
        ordinal: int,
        step_type: str,
        tool_name: str,
        arguments_json: dict[str, Any] | None,
    ) -> str:
        canonical_arguments = json.dumps(arguments_json or {}, sort_keys=True, separators=(",", ":"))
        payload = f"{task_id}|{ordinal}|{step_type}|{tool_name}|{canonical_arguments}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def tool_name_for_step(cls, step: PlanStep) -> str:
        if step.type == "tool_call":
            return f"{step.server}.{step.tool}"
        return "llm.reason_step"

    @classmethod
    def idempotency_key_for_step(
        cls,
        *,
        task_id: UUID,
        ordinal: int,
        step: PlanStep,
    ) -> str:
        arguments_json = step.args if step.type == "tool_call" else {"description": step.description}
        return cls.derive_idempotency_key(
            task_id=task_id,
            ordinal=ordinal,
            step_type=step.type,
            tool_name=cls.tool_name_for_step(step),
            arguments_json=arguments_json,
        )

    async def find_cached_completed_step(
        self,
        *,
        session: AsyncSession,
        task_id: UUID,
        idempotency_key: str,
    ) -> TaskStep | None:
        steps = list(
            (
                await session.execute(
                    select(TaskStep)
                    .where(TaskStep.task_id == task_id, TaskStep.status == StepStatus.COMPLETED)
                    .order_by(TaskStep.ordinal.asc()),
                )
            ).scalars()
        )
        for step in steps:
            input_json = step.input_json or {}
            if input_json.get("idempotency_key") == idempotency_key:
                return step
        return None

    async def prepare_replay(self, task_id: UUID) -> ReplayResult:
        async with self._session_factory() as session:
            return await self.prepare_replay_with_session(session, task_id)

    async def recount_skipped_completed_steps(self, task_id: UUID) -> int:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return 0
            return await self._count_skipped_completed_steps(session=session, task=task)

    async def prepare_replay_with_session(self, session: AsyncSession, task_id: UUID) -> ReplayResult:
        task = await session.get(Task, task_id)
        if task is None:
            raise ReplayConflictError("Task not found")
        if task.status == TaskStatus.COMPLETED:
            raise ReplayConflictError("Completed tasks cannot be replayed")
        updated_at = self._normalize_utc(task.updated_at)
        if updated_at < datetime.now(UTC) - timedelta(hours=self._max_checkpoint_age_hours):
            raise ReplayConflictError("Replay checkpoint is too old")

        skipped_completed_steps = 0
        if isinstance(task.plan, list):
            skipped_completed_steps = await self._count_skipped_completed_steps(session=session, task=task)
            if skipped_completed_steps == 0:
                skipped_completed_steps = await self._settle_and_recount(task)

            for ordinal, raw_step in enumerate(task.plan, start=1):
                step = PlanStep.model_validate(raw_step)
                key = self.idempotency_key_for_step(task_id=task.id, ordinal=ordinal, step=step)
                cached_step = await self.find_cached_completed_step(session=session, task_id=task.id, idempotency_key=key)
                if cached_step is not None:
                    continue
                if step.type == "tool_call" and not self.is_step_idempotent(step):
                    context = await self._approval_service.ensure_approval(
                        session,
                        task=task,
                        step=step,
                        assessment=RiskAssessment(
                            risk_level=RiskLevel.MEDIUM,
                            reason=f"Replay of non-idempotent tool {step.server}.{step.tool} requires operator approval.",
                            summary=f"Replay tool call {step.server}.{step.tool}",
                        ),
                        checkpoint_id=str(task.id),
                    )
                    return ReplayResult(
                        task_id=task.id,
                        status=TaskStatus.AWAITING_APPROVAL,
                        skipped_completed_steps=skipped_completed_steps,
                        approval_id=context.approval.id,
                    )

        task.status = TaskStatus.EXECUTING
        task.error = None
        task.completed_at = None
        task.checkpoint_id = str(task.id)
        await session.commit()
        await self._audit_service.record_event(
            session,
            event_type="agent.replayed",
            actor="system",
            payload={"task_id": str(task.id), "skipped_completed_steps": skipped_completed_steps},
            session_id=task.session_id,
            task_id=task.id,
        )
        return ReplayResult(task_id=task.id, status=task.status, skipped_completed_steps=skipped_completed_steps)

    @staticmethod
    def is_step_idempotent(step: PlanStep) -> bool:
        if step.type != "tool_call":
            return True
        tool_name = step.tool or ""
        non_idempotent_prefixes = ("create_", "update_", "delete_", "insert_", "write_", "drop_", "remove_", "patch_")
        if tool_name.startswith(non_idempotent_prefixes):
            return False
        return True

    @staticmethod
    def _normalize_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def _count_skipped_completed_steps(self, *, session: AsyncSession, task: Task) -> int:
        skipped_completed_steps = 0
        if not isinstance(task.plan, list):
            return skipped_completed_steps
        for ordinal, raw_step in enumerate(task.plan, start=1):
            step = PlanStep.model_validate(raw_step)
            key = self.idempotency_key_for_step(task_id=task.id, ordinal=ordinal, step=step)
            cached_step = await self.find_cached_completed_step(session=session, task_id=task.id, idempotency_key=key)
            if cached_step is not None:
                skipped_completed_steps += 1
        return skipped_completed_steps

    async def _settle_and_recount(self, task: Task) -> int:
        for _ in range(3):
            await asyncio.sleep(0.05)
            async with self._session_factory() as fresh_session:
                fresh_task = await fresh_session.get(Task, task.id)
                if fresh_task is None:
                    return 0
                skipped_completed_steps = await self._count_skipped_completed_steps(session=fresh_session, task=fresh_task)
                if skipped_completed_steps > 0:
                    return skipped_completed_steps
        return 0
