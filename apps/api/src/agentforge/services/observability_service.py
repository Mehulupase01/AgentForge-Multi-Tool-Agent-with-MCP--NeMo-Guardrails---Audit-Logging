from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.models.agent_run import AgentRun
from agentforge.models.confidence_score import ConfidenceScope, ConfidenceScore
from agentforge.models.cost_record import CostRecord
from agentforge.models.task import Task


@dataclass(slots=True)
class TimeWindow:
    start: datetime
    end: datetime


class ObservabilityService:
    async def task_cost(self, session: AsyncSession, *, task_id: UUID) -> dict:
        records = list((await session.execute(select(CostRecord).where(CostRecord.task_id == task_id))).scalars())
        by_agent: dict[str, dict] = {}
        for record in records:
            bucket = by_agent.setdefault(
                record.agent_role.value if hasattr(record.agent_role, "value") else str(record.agent_role),
                {"role": record.agent_role.value if hasattr(record.agent_role, "value") else str(record.agent_role), "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0},
            )
            bucket["prompt_tokens"] += record.prompt_tokens
            bucket["completion_tokens"] += record.completion_tokens
            bucket["usd"] += record.usd_cost
        return {
            "task_id": task_id,
            "by_agent": sorted(by_agent.values(), key=lambda item: item["role"]),
            "total_usd": round(sum(record.usd_cost for record in records), 8),
        }

    async def task_confidence(self, session: AsyncSession, *, task_id: UUID) -> dict:
        rows = list((await session.execute(select(ConfidenceScore).where(ConfidenceScore.task_id == task_id))).scalars())
        task_row = next((row for row in rows if row.scope == ConfidenceScope.TASK and row.target_id == task_id), None)
        steps = [
            {
                "step_id": row.target_id,
                "value": row.value,
                "heuristic_value": row.heuristic_value,
                "self_reported_value": row.self_reported_value,
                "factors": row.factors_json,
            }
            for row in rows
            if row.scope == ConfidenceScope.STEP
        ]
        return {
            "task_id": task_id,
            "task_confidence": task_row.value if task_row is not None else None,
            "heuristic_value": task_row.heuristic_value if task_row is not None else None,
            "self_reported_value": task_row.self_reported_value if task_row is not None else None,
            "steps": steps,
        }

    async def summary(self, session: AsyncSession, *, start: datetime | None, end: datetime | None) -> dict:
        window = self._window(start, end)
        tasks = list(
            (
                await session.execute(
                    select(Task).where(Task.created_at >= window.start, Task.created_at <= window.end)
                )
            ).scalars()
        )
        task_ids = [task.id for task in tasks]
        cost_rows = []
        confidence_rows = []
        if task_ids:
            cost_rows = list(
                (
                    await session.execute(
                        select(CostRecord).where(CostRecord.task_id.in_(task_ids), CostRecord.recorded_at >= window.start, CostRecord.recorded_at <= window.end)
                    )
                ).scalars()
            )
            confidence_rows = list(
                (
                    await session.execute(
                        select(ConfidenceScore).where(
                            ConfidenceScore.task_id.in_(task_ids),
                            ConfidenceScore.scope == ConfidenceScope.TASK,
                            ConfidenceScore.scored_at >= window.start,
                            ConfidenceScore.scored_at <= window.end,
                        )
                    )
                ).scalars()
            )

        by_agent: dict[str, dict] = {}
        for record in cost_rows:
            role = record.agent_role.value if hasattr(record.agent_role, "value") else str(record.agent_role)
            bucket = by_agent.setdefault(role, {"role": role, "tasks": set(), "usd": 0.0})
            bucket["tasks"].add(record.task_id)
            bucket["usd"] += record.usd_cost

        retry_total = 0
        scored_task_rows = [row for row in confidence_rows if row.scope == ConfidenceScope.TASK]
        for row in scored_task_rows:
            retry_total += int((row.factors_json or {}).get("retries", 0))

        return {
            "tasks": len(tasks),
            "total_usd": round(sum(row.usd_cost for row in cost_rows), 8),
            "avg_confidence": round(
                sum(row.value for row in scored_task_rows) / len(scored_task_rows),
                4,
            ) if scored_task_rows else 0.0,
            "retry_rate": round(retry_total / max(len(tasks), 1), 4),
            "by_agent": [
                {"role": role, "tasks": len(payload["tasks"]), "usd": round(payload["usd"], 8)}
                for role, payload in sorted(by_agent.items())
            ],
        }

    async def agent_handoffs(self, session: AsyncSession, *, start: datetime | None, end: datetime | None) -> dict:
        window = self._window(start, end)
        parent = AgentRun.__table__.alias("parent_agent_runs")
        child = AgentRun.__table__.alias("child_agent_runs")
        rows = await session.execute(
            select(
                parent.c.role.label("from_role"),
                child.c.role.label("to_role"),
                func.count().label("count"),
            )
            .select_from(child.join(parent, child.c.parent_run_id == parent.c.id))
            .where(child.c.created_at >= window.start, child.c.created_at <= window.end)
            .group_by(parent.c.role, child.c.role)
        )
        return {
            "edges": [
                {"from": row.from_role, "to": row.to_role, "count": int(row.count)}
                for row in rows
            ]
        }

    @staticmethod
    def _window(start: datetime | None, end: datetime | None) -> TimeWindow:
        window_end = end or datetime.now(UTC)
        window_start = start or (window_end - timedelta(days=7))
        return TimeWindow(start=window_start, end=window_end)
