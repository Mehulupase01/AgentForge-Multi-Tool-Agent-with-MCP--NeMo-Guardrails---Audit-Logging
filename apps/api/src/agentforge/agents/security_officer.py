from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.models.agent_run import AgentRole
from agentforge.models.review_record import ReviewRecord, ReviewTargetType, ReviewVerdict
from agentforge.models.task import Task
from agentforge.services.audit_service import AuditService


EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
SALARY_PATTERN = re.compile(r"\bsalary[_\s-]?band\b", re.IGNORECASE)
EMPLOYEE_DUMP_PATTERN = re.compile(r"\b(all employees|employee dump|dump employees|list every employee)\b", re.IGNORECASE)
TOOL_JOIN_PATTERN = re.compile(r"\bJOIN\b", re.IGNORECASE)


@dataclass(slots=True)
class SecurityReviewResult:
    verdict: ReviewVerdict
    rationale: str
    evidence_json: dict[str, Any]
    review_record_id: UUID | None = None


class SecurityOfficerAgent:
    def __init__(
        self,
        *,
        llm_provider,
        audit_service: AuditService | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._llm_provider = llm_provider
        self._audit_service = audit_service or AuditService()
        self._timeout_seconds = timeout_seconds

    async def review(
        self,
        session: AsyncSession,
        *,
        task: Task,
        target_type: ReviewTargetType,
        target_id: UUID,
        subject: dict[str, Any],
        requested_by: AgentRole,
    ) -> SecurityReviewResult:
        await self._audit_service.record_event(
            session,
            event_type="review.requested",
            actor=requested_by.value,
            payload={
                "task_id": str(task.id),
                "target_type": target_type.value,
                "target_id": str(target_id),
            },
            session_id=task.session_id,
            task_id=task.id,
            commit=False,
        )

        try:
            result = await asyncio.wait_for(
                self._decide(subject=subject, target_type=target_type),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            result = SecurityReviewResult(
                verdict=ReviewVerdict.REJECTED,
                rationale="SO timeout",
                evidence_json={"signals": ["timeout"]},
            )
        except asyncio.TimeoutError:
            result = SecurityReviewResult(
                verdict=ReviewVerdict.REJECTED,
                rationale="SO timeout",
                evidence_json={"signals": ["timeout"]},
            )

        review_record = ReviewRecord(
            task_id=task.id,
            target_type=target_type,
            target_id=target_id,
            reviewer_role=AgentRole.SECURITY_OFFICER.value,
            verdict=result.verdict,
            rationale=result.rationale,
            evidence_json=result.evidence_json,
            reviewed_at=datetime.now(UTC),
        )
        session.add(review_record)
        await session.flush()

        await self._audit_service.record_event(
            session,
            event_type=f"review.{result.verdict.value}",
            actor=AgentRole.SECURITY_OFFICER.value,
            payload={
                "task_id": str(task.id),
                "review_record_id": str(review_record.id),
                "target_type": target_type.value,
                "target_id": str(target_id),
                "rationale": result.rationale,
            },
            session_id=task.session_id,
            task_id=task.id,
            commit=False,
        )
        await session.commit()
        result.review_record_id = review_record.id
        return result

    async def _decide(
        self,
        *,
        subject: dict[str, Any],
        target_type: ReviewTargetType,
    ) -> SecurityReviewResult:
        heuristic = self._heuristic_review(subject=subject, target_type=target_type)
        if not hasattr(self._llm_provider, "review_security"):
            return heuristic

        response = await self._llm_provider.review_security(
            {
                "target_type": target_type.value,
                "subject": subject,
                "heuristic_verdict": heuristic.verdict.value,
                "heuristic_rationale": heuristic.rationale,
            }
        )
        payload = json.loads(response.text)
        verdict = ReviewVerdict(payload["verdict"])
        rationale = str(payload["rationale"]).strip() or heuristic.rationale
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else heuristic.evidence_json
        return SecurityReviewResult(verdict=verdict, rationale=rationale, evidence_json=evidence)

    def _heuristic_review(
        self,
        *,
        subject: dict[str, Any],
        target_type: ReviewTargetType,
    ) -> SecurityReviewResult:
        blob = json.dumps(subject, sort_keys=True, ensure_ascii=True)
        lowered = blob.lower()
        signals: list[str] = []

        if SALARY_PATTERN.search(blob):
            signals.append("salary_band_access")
        if EMPLOYEE_DUMP_PATTERN.search(blob) or ("all employees" in lowered):
            signals.append("employee_dump")
        if TOOL_JOIN_PATTERN.search(blob) and SALARY_PATTERN.search(blob):
            signals.append("sensitive_join")
        if any(token in lowered for token in ["exfiltrate", "export every", "send externally", "dump pii"]):
            signals.append("exfiltration_language")
        if target_type == ReviewTargetType.LLM_OUTPUT and EMAIL_PATTERN.search(blob):
            signals.append("email_present")
            token_count = len(str(subject.get("content", "")).split())
            if token_count >= 1000:
                return SecurityReviewResult(
                    verdict=ReviewVerdict.FLAGGED,
                    rationale="Output still contains contextual PII after redaction review.",
                    evidence_json={"signals": signals + ["long_output"]},
                )

        if signals:
            return SecurityReviewResult(
                verdict=ReviewVerdict.REJECTED,
                rationale="Security Officer rejected the request because it appears to expose sensitive employee data.",
                evidence_json={"signals": signals},
            )

        return SecurityReviewResult(
            verdict=ReviewVerdict.APPROVED,
            rationale="Security Officer approved the request as contextually safe.",
            evidence_json={"signals": ["no_contextual_risk_detected"]},
        )
