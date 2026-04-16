from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db
from agentforge.models.audit_event import AuditEvent
from agentforge.models.session import Session
from agentforge.schemas.audit import AuditEventResponse, IntegrityResponse
from agentforge.schemas.common import Envelope, Pagination
from agentforge.services.audit_service import AuditService

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
audit_service = AuditService()


def to_audit_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        sequence=event.sequence,
        session_id=event.session_id,
        task_id=event.task_id,
        event_type=event.event_type,
        actor=event.actor,
        payload=event.payload_json,
        payload_hash=event.payload_hash,
        prev_hash=event.prev_hash,
        chain_hash=event.chain_hash,
        created_at=event.created_at,
    )


@router.get("/events", response_model=Envelope[AuditEventResponse])
async def list_audit_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    event_type: list[str] | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
) -> Envelope[AuditEventResponse]:
    query = select(AuditEvent)
    count_query = select(func.count()).select_from(AuditEvent)

    if event_type:
        query = query.where(AuditEvent.event_type.in_(event_type))
        count_query = count_query.where(AuditEvent.event_type.in_(event_type))
    if session_id is not None:
        query = query.where(AuditEvent.session_id == session_id)
        count_query = count_query.where(AuditEvent.session_id == session_id)
    if task_id is not None:
        query = query.where(AuditEvent.task_id == task_id)
        count_query = count_query.where(AuditEvent.task_id == task_id)
    if from_ts is not None:
        query = query.where(AuditEvent.created_at >= from_ts)
        count_query = count_query.where(AuditEvent.created_at >= from_ts)
    if to_ts is not None:
        query = query.where(AuditEvent.created_at <= to_ts)
        count_query = count_query.where(AuditEvent.created_at <= to_ts)

    total = int((await db.execute(count_query)).scalar_one())
    events = list(
        (
            await db.execute(
                query.order_by(AuditEvent.sequence.asc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )

    return Envelope(
        data=[to_audit_response(event) for event in events],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/sessions/{session_id}/events", response_model=Envelope[AuditEventResponse])
async def list_session_audit_events(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[AuditEventResponse]:
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

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.session_id == session_id),
            )
        ).scalar_one()
    )
    events = list(
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.session_id == session_id)
                .order_by(AuditEvent.sequence.asc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )

    return Envelope(
        data=[to_audit_response(event) for event in events],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/integrity", response_model=IntegrityResponse)
async def audit_integrity(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrityResponse:
    return IntegrityResponse(**(await audit_service.verify_chain(db)))
