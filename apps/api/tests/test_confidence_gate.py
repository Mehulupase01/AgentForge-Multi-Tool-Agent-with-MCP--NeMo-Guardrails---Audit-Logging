from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from agentforge.models.agent_run import AgentRole
from agentforge.models.approval import Approval
from agentforge.models.confidence_score import ConfidenceScore, ConfidenceScope
from agentforge.models.cost_record import CostRecord
from agentforge.models.session import Session, SessionStatus
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.services.approval_service import ApprovalService
from agentforge.services.confidence_scorer import ConfidenceScorer


class NoopConfidenceProvider:
    provider_name = "mock"
    model_name = "mock-confidence"


async def create_completed_task(session_factory, prompt: str) -> Task:
    async with session_factory() as session:
        work_session = Session(
            user_id="confidence-test",
            status=SessionStatus.ACTIVE,
            started_at=datetime.now(UTC),
            metadata_json={},
        )
        session.add(work_session)
        await session.flush()
        task = Task(
            session_id=work_session.id,
            user_prompt=prompt,
            status=TaskStatus.COMPLETED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            final_response="Draft response",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


@pytest.mark.asyncio
async def test_confidence_gate_creates_approval(session_factory) -> None:
    scorer = ConfidenceScorer(
        approval_service=ApprovalService(),
        llm_provider=NoopConfidenceProvider(),
    )
    task = await create_completed_task(session_factory, "Review the project risks.")

    async with session_factory() as session:
        session.add_all(
            [
                TaskStep(
                    task_id=task.id,
                    ordinal=1,
                    step_type=StepType.RETRY,
                    description="Retry 1",
                    status=StepStatus.COMPLETED,
                    agent_role=AgentRole.ORCHESTRATOR,
                    attempt=2,
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                ),
                TaskStep(
                    task_id=task.id,
                    ordinal=2,
                    step_type=StepType.GUARDRAIL_BLOCK,
                    description="Blocked output",
                    status=StepStatus.FAILED,
                    agent_role=AgentRole.ORCHESTRATOR,
                    attempt=1,
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

        score = await scorer.score_task(session, task_id=task.id, self_reported_value=70)
        await session.commit()

        approval = (
            await session.execute(select(Approval).where(Approval.task_id == task.id))
        ).scalars().first()
        task_row = await session.get(Task, task.id)

        assert score.value < 80
        assert approval is not None
        assert approval.risk_reason == "confidence_gate"
        assert task_row is not None
        assert task_row.status == TaskStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_observability_summary_endpoint(client, session_factory) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        work_session = Session(
            user_id="summary-test",
            status=SessionStatus.ACTIVE,
            started_at=now - timedelta(hours=1),
            metadata_json={},
        )
        session.add(work_session)
        await session.flush()

        tasks: list[Task] = []
        for index in range(3):
            task = Task(
                session_id=work_session.id,
                user_prompt=f"Task {index}",
                status=TaskStatus.COMPLETED,
                started_at=now - timedelta(minutes=30 - index),
                completed_at=now - timedelta(minutes=20 - index),
                final_response="Done",
            )
            session.add(task)
            await session.flush()
            tasks.append(task)
            session.add(
                CostRecord(
                    task_id=task.id,
                    llm_call_id=None,
                    agent_role=AgentRole.ORCHESTRATOR,
                    provider="openrouter",
                    model="openrouter/free",
                    prompt_tokens=100 + index,
                    completion_tokens=50 + index,
                    usd_cost=0.001 + (index * 0.001),
                    recorded_at=now - timedelta(minutes=10 - index),
                )
            )
            session.add(
                ConfidenceScore(
                    task_id=task.id,
                    scope=ConfidenceScope.TASK,
                    target_id=task.id,
                    value=70 + index,
                    heuristic_value=68 + index,
                    self_reported_value=72 + index,
                    factors_json={"retries": index},
                    scored_at=now - timedelta(minutes=5 - index),
                )
            )
        await session.commit()

    response = await client.get("/api/v1/observability/summary")
    payload = response.json()

    assert response.status_code == 200
    assert payload["tasks"] == 3
    assert payload["total_usd"] > 0
    assert payload["avg_confidence"] > 0
