from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.models.approval import Approval, ApprovalDecision, RiskLevel
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.schemas.task import PlanStep
from agentforge.services.audit_service import AuditService

SAFE_FETCH_HOSTS = {
    "docs.github.com",
    "example.com",
    "github.com",
    "news.ycombinator.com",
    "openrouter.ai",
}
LOW_RISK_TOOLS = {
    ("file_search", "search_corpus"),
    ("file_search", "read_document"),
    ("web_fetch", "weather_for"),
    ("web_fetch", "hacker_news_top"),
    ("github", "list_user_repos"),
    ("github", "search_issues"),
    ("github", "get_repo"),
}
WRITE_TOOL_PREFIXES = ("create_", "update_", "delete_", "insert_", "write_", "drop_", "remove_", "patch_")
WRITE_TOOL_NAMES = {"create", "update", "delete", "insert", "write", "drop", "remove", "patch"}
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


@dataclass(slots=True)
class RiskAssessment:
    risk_level: RiskLevel
    reason: str
    summary: str

    @property
    def requires_approval(self) -> bool:
        return self.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH}


@dataclass(slots=True)
class ApprovalContext:
    approval: Approval
    gate_step: TaskStep
    assessment: RiskAssessment
    created: bool


class ApprovalService:
    def __init__(self, audit_service: AuditService | None = None) -> None:
        self._audit_service = audit_service or AuditService()
        self._wake_queues: dict[str, asyncio.Queue[str]] = {}
        self._queue_lock = asyncio.Lock()

    def classify_tool_call(self, step: PlanStep) -> RiskAssessment:
        server_name = step.server or ""
        tool_name = step.tool or ""
        arguments = step.args
        summary = self._summarize_action(step)

        if (server_name, tool_name) in LOW_RISK_TOOLS:
            return RiskAssessment(RiskLevel.LOW, "Read-only tool call does not require approval.", summary)

        if server_name == "sqlite_query" and tool_name.startswith("list_"):
            return RiskAssessment(RiskLevel.LOW, "Read-only list query does not require approval.", summary)

        if server_name == "web_fetch" and tool_name == "fetch_url":
            host = (urlparse(str(arguments.get("url", ""))).hostname or "").lower()
            if host and host in SAFE_FETCH_HOSTS:
                return RiskAssessment(RiskLevel.LOW, f"Host '{host}' is in the static fetch allowlist.", summary)
            return RiskAssessment(
                RiskLevel.MEDIUM,
                f"External fetch to host '{host or 'unknown'}' requires human approval.",
                summary,
            )

        if server_name == "sqlite_query" and tool_name == "run_select":
            sql = str(arguments.get("sql", ""))
            normalized = sql.upper()
            limit_match = LIMIT_PATTERN.search(sql)
            limit_value = int(limit_match.group(1)) if limit_match else None
            if "JOIN" in normalized and "SALARY_BAND" in normalized:
                return RiskAssessment(
                    RiskLevel.MEDIUM,
                    "SQL joins against salary_band require human approval.",
                    summary,
                )
            if limit_value is None:
                return RiskAssessment(
                    RiskLevel.MEDIUM,
                    "Arbitrary SELECT without LIMIT requires human approval.",
                    summary,
                )
            if limit_value > 100:
                return RiskAssessment(
                    RiskLevel.MEDIUM,
                    "Arbitrary SELECT with LIMIT greater than 100 requires human approval.",
                    summary,
                )
            return RiskAssessment(RiskLevel.LOW, "Bounded SELECT is safe to run without approval.", summary)

        lowered_tool = tool_name.lower()
        if lowered_tool in WRITE_TOOL_NAMES or lowered_tool.startswith(WRITE_TOOL_PREFIXES):
            return RiskAssessment(
                RiskLevel.HIGH,
                "Write-capable tools always require approval.",
                summary,
            )

        return RiskAssessment(RiskLevel.LOW, "Tool classified as low-risk by default allowlist rules.", summary)

    async def ensure_approval(
        self,
        session: AsyncSession,
        *,
        task: Task,
        step: PlanStep,
        assessment: RiskAssessment,
        checkpoint_id: str,
    ) -> ApprovalContext:
        approval = await self._get_matching_approval(session, task.id, assessment.summary)
        created = False
        if approval is None:
            approval = Approval(
                task_id=task.id,
                risk_level=assessment.risk_level,
                risk_reason=assessment.reason,
                action_summary=assessment.summary,
                requested_at=datetime.now(UTC),
                decision=ApprovalDecision.PENDING,
            )
            session.add(approval)
            await session.flush()
            created = True

        gate_step = await self._get_gate_step(session, approval, assessment.summary)
        if gate_step is None:
            gate_step = TaskStep(
                task_id=task.id,
                ordinal=await self.next_ordinal(session, task.id),
                step_type=StepType.APPROVAL_GATE,
                description=f"Approval required: {assessment.summary}",
                status=StepStatus.PENDING,
                input_json={
                    "step_id": step.step_id,
                    "server": step.server,
                    "tool": step.tool,
                    "args": step.args,
                    "risk_level": assessment.risk_level.value,
                    "risk_reason": assessment.reason,
                },
                output_json=None,
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            session.add(gate_step)
            await session.flush()
            approval.task_step_id = gate_step.id
        elif approval.task_step_id is None:
            approval.task_step_id = gate_step.id

        if approval.decision == ApprovalDecision.PENDING:
            task.status = TaskStatus.AWAITING_APPROVAL
            task.checkpoint_id = checkpoint_id

        if created:
            await self._audit_service.record_event(
                session,
                event_type="approval.requested",
                actor="system",
                payload={
                    "task_id": str(task.id),
                    "approval_id": str(approval.id),
                    "risk_level": approval.risk_level.value,
                    "action_summary": approval.action_summary,
                },
                session_id=task.session_id,
                task_id=task.id,
                commit=False,
            )

        await session.commit()
        return ApprovalContext(approval=approval, gate_step=gate_step, assessment=assessment, created=created)

    async def decide(
        self,
        session: AsyncSession,
        *,
        approval: Approval,
        decision: ApprovalDecision,
        rationale: str | None,
        decided_by: str,
    ) -> Approval:
        approval.decision = decision
        approval.rationale = rationale
        approval.decided_by = decided_by
        approval.decided_at = datetime.now(UTC)
        await self._audit_service.record_event(
            session,
            event_type="approval.decided",
            actor=decided_by,
            payload={
                "task_id": str(approval.task_id),
                "approval_id": str(approval.id),
                "decision": decision.value,
                "rationale": rationale,
            },
            task_id=approval.task_id,
            commit=False,
        )
        await session.commit()
        return approval

    async def mark_gate_approved(self, session: AsyncSession, approval: Approval) -> None:
        task = await session.get(Task, approval.task_id)
        if task is not None:
            task.status = TaskStatus.EXECUTING

        if approval.task_step_id is None:
            await session.flush()
            return

        gate_step = await session.get(TaskStep, approval.task_step_id)
        if gate_step is None:
            await session.flush()
            return

        gate_step.status = StepStatus.COMPLETED
        gate_step.completed_at = datetime.now(UTC)
        gate_step.output_json = {
            "approval_id": str(approval.id),
            "decision": approval.decision.value,
            "rationale": approval.rationale,
        }
        await session.flush()

    async def apply_rejection(self, session: AsyncSession, approval: Approval) -> tuple[str, str]:
        task = await session.get(Task, approval.task_id)
        rejection_reason = approval.rationale or approval.risk_reason
        if task is not None:
            task.status = TaskStatus.REJECTED
            task.error = rejection_reason
            task.completed_at = datetime.now(UTC)

        description = approval.action_summary
        if approval.task_step_id is not None:
            gate_step = await session.get(TaskStep, approval.task_step_id)
            if gate_step is not None:
                gate_step.status = StepStatus.FAILED
                gate_step.completed_at = datetime.now(UTC)
                gate_step.output_json = {
                    "approval_id": str(approval.id),
                    "decision": approval.decision.value,
                    "rationale": approval.rationale,
                }
                description = gate_step.description

        await session.flush()
        return rejection_reason, description

    async def get_by_id(self, session: AsyncSession, approval_id: UUID) -> Approval | None:
        return await session.get(Approval, approval_id)

    async def get_latest_for_task(self, session: AsyncSession, task_id: UUID) -> Approval | None:
        return (
            await session.execute(
                select(Approval)
                .where(Approval.task_id == task_id)
                .order_by(Approval.requested_at.desc()),
            )
        ).scalars().first()

    async def get_latest_decided_for_task(self, session: AsyncSession, task_id: UUID) -> Approval | None:
        return (
            await session.execute(
                select(Approval)
                .where(Approval.task_id == task_id, Approval.decision != ApprovalDecision.PENDING)
                .order_by(Approval.requested_at.desc()),
            )
        ).scalars().first()

    async def signal_resume(self, task_id: UUID | str, approval_id: UUID | str) -> None:
        async with self._queue_lock:
            queue = self._wake_queues.setdefault(str(task_id), asyncio.Queue())
        await queue.put(str(approval_id))

    async def wait_for_resume(self, task_id: UUID | str) -> str:
        async with self._queue_lock:
            queue = self._wake_queues.setdefault(str(task_id), asyncio.Queue())
        return await queue.get()

    async def close(self) -> None:
        async with self._queue_lock:
            self._wake_queues.clear()

    async def next_ordinal(self, session: AsyncSession, task_id: UUID) -> int:
        current_max = (
            await session.execute(
                select(func.max(TaskStep.ordinal)).where(TaskStep.task_id == task_id),
            )
        ).scalar_one()
        return int(current_max or 0) + 1

    async def _get_matching_approval(
        self,
        session: AsyncSession,
        task_id: UUID,
        action_summary: str,
    ) -> Approval | None:
        return (
            await session.execute(
                select(Approval)
                .where(Approval.task_id == task_id, Approval.action_summary == action_summary)
                .order_by(Approval.requested_at.desc()),
            )
        ).scalars().first()

    async def _get_gate_step(
        self,
        session: AsyncSession,
        approval: Approval,
        action_summary: str,
    ) -> TaskStep | None:
        if approval.task_step_id is not None:
            step = await session.get(TaskStep, approval.task_step_id)
            if step is not None:
                return step

        description = f"Approval required: {action_summary}"
        return (
            await session.execute(
                select(TaskStep)
                .where(
                    TaskStep.task_id == approval.task_id,
                    TaskStep.step_type == StepType.APPROVAL_GATE,
                    TaskStep.description == description,
                )
                .order_by(TaskStep.ordinal.desc()),
            )
        ).scalars().first()

    @staticmethod
    def _summarize_action(step: PlanStep) -> str:
        args = json.dumps(step.args, sort_keys=True, ensure_ascii=True)
        if len(args) > 200:
            args = f"{args[:197]}..."
        return f"{step.description} [{step.server}.{step.tool}] args={args}"


_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
