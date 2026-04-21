from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db
from agentforge.schemas.observability import (
    AgentHandoffEdge,
    AgentHandoffsResponse,
    ObservabilitySummaryResponse,
    TaskConfidenceResponse,
    TaskCostResponse,
)
from agentforge.services.observability_service import ObservabilityService

router = APIRouter(prefix="/api/v1/observability", tags=["observability"])
service = ObservabilityService()


@router.get("/tasks/{task_id}/cost", response_model=TaskCostResponse)
async def get_task_cost(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskCostResponse:
    payload = await service.task_cost(db, task_id=task_id)
    return TaskCostResponse.model_validate(payload)


@router.get("/tasks/{task_id}/confidence", response_model=TaskConfidenceResponse)
async def get_task_confidence(
    task_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskConfidenceResponse:
    payload = await service.task_confidence(db, task_id=task_id)
    return TaskConfidenceResponse.model_validate(payload)


@router.get("/summary", response_model=ObservabilitySummaryResponse)
async def get_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    from_timestamp: datetime | None = Query(default=None, alias="from"),
    to_timestamp: datetime | None = Query(default=None, alias="to"),
) -> ObservabilitySummaryResponse:
    payload = await service.summary(db, start=from_timestamp, end=to_timestamp)
    return ObservabilitySummaryResponse.model_validate(payload)


@router.get("/agent_handoffs", response_model=AgentHandoffsResponse)
async def get_agent_handoffs(
    db: Annotated[AsyncSession, Depends(get_db)],
    from_timestamp: datetime | None = Query(default=None, alias="from"),
    to_timestamp: datetime | None = Query(default=None, alias="to"),
) -> AgentHandoffsResponse:
    payload = await service.agent_handoffs(db, start=from_timestamp, end=to_timestamp)
    return AgentHandoffsResponse(edges=[AgentHandoffEdge.from_payload(item) for item in payload["edges"]])
