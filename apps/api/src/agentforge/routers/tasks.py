from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from agentforge.database import get_db, get_session_factory
from agentforge.models.session import Session
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import TaskStep
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.task import TaskCreate, TaskResponse, TaskStepResponse
from agentforge.services.agent_orchestrator import AgentOrchestrator, get_agent_orchestrator
from agentforge.services.audit_service import AuditService
from agentforge.services.llm_provider import LLMProvider, get_llm_provider
from agentforge.services.mcp_client_pool import MCPClientPool, get_mcp_client_pool
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus

router = APIRouter(prefix="/api/v1", tags=["tasks"])
audit_service = AuditService()


def to_task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        session_id=task.session_id,
        user_prompt=task.user_prompt,
        plan=task.plan,
        status=task.status,
        started_at=task.started_at,
        completed_at=task.completed_at,
        final_response=task.final_response,
        error=task.error,
        checkpoint_id=task.checkpoint_id,
    )


def to_task_step_response(step: TaskStep) -> TaskStepResponse:
    return TaskStepResponse(
        id=step.id,
        task_id=step.task_id,
        ordinal=step.ordinal,
        step_type=step.step_type,
        description=step.description,
        status=step.status,
        input_json=step.input_json,
        output_json=step.output_json,
        started_at=step.started_at,
        completed_at=step.completed_at,
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
    task = await db.get(Task, task_id)
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
) -> AgentOrchestrator:
    return get_agent_orchestrator(
        session_factory=get_session_factory(),
        mcp_pool=mcp_pool,
        llm_provider=llm_provider,
        event_bus=event_bus,
    )


@router.post("/sessions/{session_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    session_id: UUID,
    body: TaskCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
) -> TaskResponse:
    session = await require_session(db, session_id)
    task = Task(
        session_id=session.id,
        user_prompt=body.user_prompt,
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

    orchestrator.start_task(task.id)
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
        if history and history[-1]["event"] in {"task_completed", "task_failed"}:
            return

        async with event_bus.subscribe(task_id) as queue:
            while True:
                item = await queue.get()
                yield {"event": item["event"], "data": json.dumps(item["data"], ensure_ascii=True)}
                if item["event"] in {"task_completed", "task_failed"}:
                    break

    return EventSourceResponse(event_generator())


@router.post("/tasks/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    task = await require_task(db, task_id)
    return to_task_response(task)
