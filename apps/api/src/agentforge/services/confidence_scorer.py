from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentforge.config import settings
from agentforge.models.agent_run import AgentRole, AgentRun
from agentforge.models.approval import Approval, ApprovalDecision, RiskLevel
from agentforge.models.confidence_score import ConfidenceScope, ConfidenceScore
from agentforge.models.review_record import ReviewRecord, ReviewVerdict
from agentforge.models.skill import SkillInvocation
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.llm_provider import LLMProvider


@dataclass(slots=True)
class ConfidenceComputation:
    heuristic_value: float
    final_value: float
    self_reported_value: float | None
    factors: dict[str, Any]
    self_report_reasoning: str | None = None


class ConfidenceScorer:
    def __init__(
        self,
        *,
        approval_service: ApprovalService,
        llm_provider: LLMProvider,
        audit_service: AuditService | None = None,
    ) -> None:
        self._approval_service = approval_service
        self._llm_provider = llm_provider
        self._audit_service = audit_service or AuditService()

    @staticmethod
    def heuristic_from_factors(
        *,
        retry_count: int,
        guardrail_block_count: int,
        review_flagged_count: int,
        review_rejected_count_recovered: int,
        successful_skill_policy_checks: int,
    ) -> float:
        heuristic = (
            100.0
            - (15.0 * retry_count)
            - (10.0 * guardrail_block_count)
            - (20.0 * review_flagged_count)
            - (25.0 * review_rejected_count_recovered)
            + (5.0 * successful_skill_policy_checks)
        )
        return max(0.0, min(100.0, heuristic))

    @staticmethod
    def merge_with_self_report(heuristic_value: float, self_reported_value: float | None) -> float:
        if self_reported_value is None:
            return heuristic_value
        merged = (0.6 * heuristic_value) + (0.4 * self_reported_value)
        return max(0.0, min(100.0, merged))

    async def score_task(
        self,
        session: AsyncSession,
        *,
        task_id: UUID,
        self_reported_value: float | None = None,
        self_report_reasoning: str | None = None,
        commit: bool = False,
    ) -> ConfidenceScore:
        task = (
            await session.execute(
                select(Task)
                .options(
                    selectinload(Task.steps).selectinload(TaskStep.skill_invocations),
                    selectinload(Task.agent_runs),
                    selectinload(Task.approvals),
                    selectinload(Task.review_records),
                    selectinload(Task.confidence_scores),
                )
                .where(Task.id == task_id),
            )
        ).scalars().first()
        if task is None:
            raise RuntimeError(f"Task {task_id} not found for confidence scoring.")

        if self_reported_value is None:
            self_reported_value, self_report_reasoning = await self._request_self_report(task)

        factors = self._task_factors(task)
        task_score = await self._upsert_confidence(
            session,
            task=task,
            scope=ConfidenceScope.TASK,
            target_id=task.id,
            computation=self._build_computation(
                factors=factors,
                self_reported_value=self_reported_value,
                self_report_reasoning=self_report_reasoning,
            ),
        )

        for step in task.steps:
            await self._upsert_confidence(
                session,
                task=task,
                scope=ConfidenceScope.STEP,
                target_id=step.id,
                computation=self._build_computation(
                    factors=self._step_factors(step, task.review_records),
                    self_reported_value=None,
                    self_report_reasoning=None,
                ),
            )

        for agent_run in task.agent_runs:
            await self._upsert_confidence(
                session,
                task=task,
                scope=ConfidenceScope.AGENT_RUN,
                target_id=agent_run.id,
                computation=self._build_computation(
                    factors=self._agent_run_factors(agent_run, task.steps, task.review_records),
                    self_reported_value=None,
                    self_report_reasoning=None,
                ),
            )

        if task.status == TaskStatus.COMPLETED:
            await self._apply_confidence_gate(session, task=task, task_score=task_score)
        if commit:
            await session.commit()
        return task_score

    async def _upsert_confidence(
        self,
        session: AsyncSession,
        *,
        task: Task,
        scope: ConfidenceScope,
        target_id: UUID,
        computation: ConfidenceComputation,
    ) -> ConfidenceScore:
        existing = (
            await session.execute(
                select(ConfidenceScore).where(
                    ConfidenceScore.task_id == task.id,
                    ConfidenceScore.scope == scope,
                    ConfidenceScore.target_id == target_id,
                )
            )
        ).scalars().first()
        record = existing or ConfidenceScore(
            task_id=task.id,
            scope=scope,
            target_id=target_id,
            value=computation.final_value,
            heuristic_value=computation.heuristic_value,
            self_reported_value=computation.self_reported_value,
            factors_json=computation.factors,
            scored_at=datetime.now(UTC),
        )
        record.value = computation.final_value
        record.heuristic_value = computation.heuristic_value
        record.self_reported_value = computation.self_reported_value
        record.factors_json = computation.factors
        record.scored_at = datetime.now(UTC)
        session.add(record)
        await session.flush()

        await self._audit_service.record_event(
            session,
            event_type="confidence.scored",
            actor="system",
            payload={
                "task_id": str(task.id),
                "scope": scope.value,
                "target_id": str(target_id),
                "value": round(record.value, 4),
                "heuristic_value": round(record.heuristic_value, 4),
                "self_reported_value": record.self_reported_value,
                "factors": computation.factors,
            },
            session_id=task.session_id,
            task_id=task.id,
            commit=False,
        )
        return record

    async def _apply_confidence_gate(
        self,
        session: AsyncSession,
        *,
        task: Task,
        task_score: ConfidenceScore,
    ) -> None:
        threshold = settings.confidence_gate_threshold
        if task_score.value >= threshold:
            return

        existing = next((approval for approval in task.approvals if approval.risk_reason == "confidence_gate"), None)
        if existing is not None:
            if existing.decision == ApprovalDecision.PENDING:
                task.status = TaskStatus.AWAITING_APPROVAL
            return

        gate_step = TaskStep(
            task_id=task.id,
            ordinal=await self._approval_service.next_ordinal(session, task.id),
            step_type=StepType.APPROVAL_GATE,
            description="Approval required: Review low-confidence task result.",
            status=StepStatus.PENDING,
            agent_role=AgentRole.ORCHESTRATOR,
            attempt=1,
            input_json={
                "confidence": task_score.value,
                "threshold": threshold,
            },
            output_json=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        session.add(gate_step)
        await session.flush()

        approval = Approval(
            task_id=task.id,
            task_step_id=gate_step.id,
            risk_level=RiskLevel.LOW,
            risk_reason="confidence_gate",
            action_summary="Operator review required for a low-confidence task result.",
            requested_at=datetime.now(UTC),
            decision=ApprovalDecision.PENDING,
        )
        session.add(approval)
        task.status = TaskStatus.AWAITING_APPROVAL
        task.completed_at = None
        await session.flush()
        await self._audit_service.record_event(
            session,
            event_type="approval.requested",
            actor="system",
            payload={
                "task_id": str(task.id),
                "approval_id": str(approval.id),
                "risk_level": approval.risk_level.value,
                "action_summary": approval.action_summary,
                "reason": "confidence_gate",
            },
            session_id=task.session_id,
            task_id=task.id,
            commit=False,
        )

    async def _request_self_report(self, task: Task) -> tuple[float | None, str | None]:
        if not hasattr(self._llm_provider, "assess_confidence"):
            return None, None
        try:
            payload = {
                "user_prompt": task.user_prompt,
                "final_response": task.final_response or "",
                "status": task.status.value,
            }
            response = await self._llm_provider.assess_confidence(payload)
            parsed = json.loads(response.text)
            confidence = float(parsed["confidence"])
            return max(0.0, min(100.0, confidence)), str(parsed.get("reasoning", "")).strip() or None
        except Exception:
            return None, None

    def _build_computation(
        self,
        *,
        factors: dict[str, Any],
        self_reported_value: float | None,
        self_report_reasoning: str | None,
    ) -> ConfidenceComputation:
        heuristic_value = self.heuristic_from_factors(
            retry_count=int(factors.get("retries", 0)),
            guardrail_block_count=int(factors.get("guardrail_blocks", 0)),
            review_flagged_count=int(factors.get("review_flagged", 0)),
            review_rejected_count_recovered=int(factors.get("review_rejected_recovered", 0)),
            successful_skill_policy_checks=int(factors.get("successful_skill_policy_checks", 0)),
        )
        return ConfidenceComputation(
            heuristic_value=heuristic_value,
            final_value=self.merge_with_self_report(heuristic_value, self_reported_value),
            self_reported_value=self_reported_value,
            factors={
                **factors,
                "self_report_reasoning": self_report_reasoning,
            },
            self_report_reasoning=self_report_reasoning,
        )

    def _task_factors(self, task: Task) -> dict[str, Any]:
        return {
            "retries": sum(1 for step in task.steps if step.step_type == StepType.RETRY),
            "guardrail_blocks": sum(1 for step in task.steps if step.step_type == StepType.GUARDRAIL_BLOCK),
            "review_flagged": sum(1 for review in task.review_records if review.verdict == ReviewVerdict.FLAGGED),
            "review_rejected_recovered": sum(
                1
                for approval in task.approvals
                if approval.risk_reason.startswith("security_officer_rejected:")
                and approval.decision == ApprovalDecision.APPROVED
            ),
            "successful_skill_policy_checks": sum(self._count_successful_policy_checks(step.skill_invocations) for step in task.steps),
        }

    def _agent_run_factors(
        self,
        agent_run: AgentRun,
        steps: list[TaskStep],
        reviews: list[ReviewRecord],
    ) -> dict[str, Any]:
        run_steps = [step for step in steps if step.agent_run_id == agent_run.id]
        return {
            "retries": sum(1 for step in run_steps if step.step_type == StepType.RETRY),
            "guardrail_blocks": sum(1 for step in run_steps if step.step_type == StepType.GUARDRAIL_BLOCK),
            "review_flagged": sum(
                1
                for review in reviews
                if review.verdict == ReviewVerdict.FLAGGED and review.target_id == agent_run.id
            ),
            "review_rejected_recovered": sum(
                1
                for review in reviews
                if review.verdict == ReviewVerdict.REJECTED and review.target_id == agent_run.id
            ),
            "successful_skill_policy_checks": sum(self._count_successful_policy_checks(step.skill_invocations) for step in run_steps),
        }

    def _step_factors(self, step: TaskStep, reviews: list[ReviewRecord]) -> dict[str, Any]:
        return {
            "retries": max(0, step.attempt - 1),
            "guardrail_blocks": 1 if step.step_type == StepType.GUARDRAIL_BLOCK else 0,
            "review_flagged": sum(
                1
                for review in reviews
                if review.verdict == ReviewVerdict.FLAGGED and review.target_id == step.id
            ),
            "review_rejected_recovered": 0,
            "successful_skill_policy_checks": self._count_successful_policy_checks(step.skill_invocations),
        }

    @staticmethod
    def _count_successful_policy_checks(invocations: list[SkillInvocation]) -> int:
        passed = 0
        for invocation in invocations:
            checks = invocation.policy_checks_json or {}
            if checks and all(bool(value.get("pass")) for value in checks.values() if isinstance(value, dict)):
                passed += 1
        return passed
