from __future__ import annotations

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from agentforge.models.agent_run import AgentRole, AgentRun
from agentforge.database import get_db
from agentforge.guardrails import GuardrailsRunner, get_guardrails_runner
from agentforge.models.review_record import ReviewRecord
from agentforge.models.session import Session
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.agent import AgentRunResponse, AgentRunSummary, ReviewRecordResponse
from agentforge.schemas.task import ReplayRequest, ReplayResponse, TaskCreate, TaskResponse, TaskStepResponse
from agentforge.services.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
from agentforge.services.approval_service import ApprovalService, get_approval_service
from agentforge.services.audit_service import AuditService
from agentforge.services.llm_provider import LLMProvider, get_llm_provider
from agentforge.services.mcp_client_pool import MCPClientPool, get_mcp_client_pool
from agentforge.services.replay_service import ReplayConflictError, ReplayService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus

router = APIRouter(prefix="/api/v1", tags=["tasks"])
audit_service = AuditService()


def to_task_response(task: Task) -> TaskResponse:
    agent_runs = list(task.__dict__.get("agent_runs") or [])
    serialized_plan = task.plan if isinstance(task.plan, list) else None
    supervisor_plan = task.plan if isinstance(task.plan, dict) and "handoffs" in task.plan else None
    for agent_run in reversed(agent_runs):
        if agent_run.role == AgentRole.ORCHESTRATOR and isinstance(agent_run.result_json, dict) and "handoffs" in agent_run.result_json:
            supervisor_plan = agent_run.result_json
            break
    return TaskResponse(
        id=task.id,
        session_id=task.session_id,
        user_prompt=task.user_prompt,
        plan=serialized_plan,
        supervisor_plan=supervisor_plan,
        status=task.status,
        started_at=task.started_at,
        completed_at=task.completed_at,
        final_response=task.final_response,
        error=task.error,
        checkpoint_id=task.checkpoint_id,
        agent_runs=[
            AgentRunSummary(
                id=agent_run.id,
                role=agent_run.role,
                status=agent_run.status,
                started_at=agent_run.started_at,
                completed_at=agent_run.completed_at,
                handoff_reason=agent_run.handoff_reason,
            )
            for agent_run in agent_runs
        ],
    )


def to_task_step_response(step: TaskStep) -> TaskStepResponse:
    return TaskStepResponse(
        id=step.id,
        task_id=step.task_id,
        ordinal=step.ordinal,
        step_type=step.step_type,
        description=step.description,
        status=step.status,
        agent_role=step.agent_role,
        attempt=step.attempt,
        parent_step_id=step.parent_step_id,
        agent_run_id=step.agent_run_id,
        input_json=step.input_json,
        output_json=step.output_json,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def to_agent_run_response(agent_run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=agent_run.id,
        task_id=agent_run.task_id,
        role=agent_run.role,
        parent_run_id=agent_run.parent_run_id,
        handoff_reason=agent_run.handoff_reason,
        handoff_payload_json=agent_run.handoff_payload_json,
        started_at=agent_run.started_at,
        completed_at=agent_run.completed_at,
        status=agent_run.status,
        result_json=agent_run.result_json,
    )


def to_review_record_response(record: ReviewRecord) -> ReviewRecordResponse:
    return ReviewRecordResponse(
        id=record.id,
        task_id=record.task_id,
        target_type=record.target_type,
        target_id=record.target_id,
        reviewer_role=record.reviewer_role,
        verdict=record.verdict,
        rationale=record.rationale,
        evidence_json=record.evidence_json,
        reviewed_at=record.reviewed_at,
    )


async def require_session(db: AsyncSession, session_id: UUID) -> Session:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Session not found",
                "detail": {"session_id": str(session_id)},
            },
        )
    return session


async def require_task(db: AsyncSession, task_id: UUID) -> Task:
    task = (
        await db.execute(
            select(Task)
            .options(selectinload(Task.agent_runs))
            .where(Task.id == task_id),
        )
    ).scalars().first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Task not found",
                "detail": {"task_id": str(task_id)},
            },
        )
    return task


def orchestrator_dependency(
    mcp_pool: Annotated[MCPClientPool, Depends(get_mcp_client_pool)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    event_bus: Annotated[TaskEventBus, Depends(get_task_event_bus)],
    guardrails_runner: Annotated[GuardrailsRunner, Depends(get_guardrails_runner)],
    approval_service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> AgentOrchestrator:
    return get_agent_orchestrator(
        session_factory=get_session_factory(),
        mcp_pool=mcp_pool,
        llm_provider=llm_provider,
        event_bus=event_bus,
        guardrails_runner=guardrails_runner,
        approval_service=approval_service,
    )


@router.post("/sessions/{session_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    session_id: UUID,
    body: TaskCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
    guardrails_runner: Annotated[GuardrailsRunner, Depends(get_guardrails_runner)],
) -> TaskResponse:
    session = await require_session(db, session_id)
    processed_input = guardrails_runner.process_input(body.user_prompt)
    if processed_input.pii.get("redacted"):
        await audit_service.record_guardrail_event(
            db,
            event_type="guardrail.pii_redacted",
            payload={"session_id": str(session_id), "entities": processed_input.pii["entities"]},
            session_id=session.id,
            commit=False,
        )
    if processed_input.injection.get("blocked"):
        await audit_service.record_guardrail_event(
            db,
            event_type="guardrail.injection_detected",
            payload={"session_id": str(session_id), "matched_patterns": processed_input.injection["matched_patterns"]},
            session_id=session.id,
            commit=False,
        )
    if processed_input.blocked:
        task = Task(
            session_id=session.id,
            user_prompt=processed_input.text,
            status=TaskStatus.REJECTED,
            error=processed_input.reason,
        )
        db.add(task)
        await db.flush()
        db.add(
            TaskStep(
                task_id=task.id,
                ordinal=1,
                step_type=StepType.GUARDRAIL_BLOCK,
                description=processed_input.reason or "Input blocked by guardrails",
                status=StepStatus.FAILED,
                input_json={"prompt": processed_input.original_text},
                output_json=processed_input.input_rails_json(),
            ),
        )
        await audit_service.record_guardrail_event(
            db,
            event_type="guardrail.input_blocked",
            payload={
                "task_id": str(task.id),
                "session_id": str(session_id),
                "reason": processed_input.reason,
            },
            session_id=session.id,
            task_id=task.id,
            commit=False,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "GUARDRAIL_BLOCKED",
                "message": processed_input.reason or "Input blocked by guardrails",
                "detail": {"task_id": str(task.id), "session_id": str(session.id)},
            },
        )

    task = Task(
        session_id=session.id,
        user_prompt=processed_input.text,
        status=TaskStatus.PLANNING,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    await audit_service.record_event(
        db,
        event_type="task.created",
        actor=request.state.user_id,
        payload={
            "task_id": str(task.id),
            "session_id": str(session_id),
            "status": task.status.value,
        },
        session_id=session.id,
        task_id=task.id,
    )

    orchestrator.start_task(task.id, input_rails=processed_input.input_rails_json())
    return to_task_response(task)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    task = await require_task(db, task_id)
    return to_task_response(task)


@router.get("/tasks/{task_id}/steps", response_model=Envelope[TaskStepResponse])
async def list_task_steps(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[TaskStepResponse]:
    await require_task(db, task_id)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(TaskStep).where(TaskStep.task_id == task_id),
            )
        ).scalar_one()
    )
    steps = list(
        (
            await db.execute(
                select(TaskStep)
                .where(TaskStep.task_id == task_id)
                .order_by(TaskStep.ordinal.asc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )
    return Envelope(
        data=[to_task_step_response(step) for step in steps],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/tasks/{task_id}/agents", response_model=Envelope[AgentRunResponse])
async def list_task_agents(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[AgentRunResponse]:
    await require_task(db, task_id)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(AgentRun).where(AgentRun.task_id == task_id),
            )
        ).scalar_one()
    )
    runs = list(
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.task_id == task_id)
                .order_by(AgentRun.started_at.asc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )
    return Envelope(
        data=[to_agent_run_response(run) for run in runs],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/tasks/{task_id}/reviews", response_model=Envelope[ReviewRecordResponse])
async def list_task_reviews(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[ReviewRecordResponse]:
    await require_task(db, task_id)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(ReviewRecord).where(ReviewRecord.task_id == task_id),
            )
        ).scalar_one()
    )
    records = list(
        (
            await db.execute(
                select(ReviewRecord)
                .where(ReviewRecord.task_id == task_id)
                .order_by(ReviewRecord.reviewed_at.asc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )
    return Envelope(
        data=[to_review_record_response(record) for record in records],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    event_bus: Annotated[TaskEventBus, Depends(get_task_event_bus)],
):
    await require_task(db, task_id)

    async def event_generator():
        history = await event_bus.get_history(task_id)
        for item in history:
            yield {"event": item["event"], "data": json.dumps(item["data"], ensure_ascii=True)}
        if history and history[-1]["event"] in {"task_completed", "task_failed", "task_rejected"}:
            return

        async with event_bus.subscribe(task_id) as queue:
            while True:
                item = await queue.get()
                yield {"event": item["event"], "data": json.dumps(item["data"], ensure_ascii=True)}
                if item["event"] in {"task_completed", "task_failed", "task_rejected"}:
                    break

    return EventSourceResponse(event_generator())


@router.post("/tasks/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
) -> TaskResponse:
    task = await require_task(db, task_id)
    await orchestrator.resume_task(task.id)
    task = await require_task(db, task_id)
    return to_task_response(task)


@router.post("/tasks/{task_id}/replay", response_model=ReplayResponse, status_code=status.HTTP_202_ACCEPTED)
async def replay_task(
    task_id: UUID,
    body: ReplayRequest,
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
    approval_service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> ReplayResponse:
    await orchestrator.wait_until_idle(task_id)
    async with orchestrator.session_factory() as replay_db:
        await require_task(replay_db, task_id)
        replay_service = ReplayService(
            session_factory=orchestrator.session_factory,
            approval_service=approval_service,
            audit_service=audit_service,
        )
        try:
            result = await replay_service.prepare_replay_with_session(replay_db, task_id)
        except ReplayConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "CONFLICT",
                    "message": str(exc),
                    "detail": {"task_id": str(task_id), "from_checkpoint": body.from_checkpoint},
                },
            ) from exc
        if result.skipped_completed_steps == 0:
            for _ in range(3):
                await asyncio.sleep(0.05)
                recounted = await replay_service.recount_skipped_completed_steps(task_id)
                if recounted > 0:
                    result.skipped_completed_steps = recounted
                    break

    if result.status == TaskStatus.AWAITING_APPROVAL:
        return ReplayResponse(
            task_id=result.task_id,
            status=result.status,
            skipped_completed_steps=result.skipped_completed_steps,
            approval_id=result.approval_id,
        )

    orchestrator.replay_task(task_id)
    return ReplayResponse(
        task_id=result.task_id,
        status=result.status,
        skipped_completed_steps=result.skipped_completed_steps,
        approval_id=result.approval_id,
    )
