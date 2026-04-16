from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db
from agentforge.models.session import Session, SessionStatus
from agentforge.models.task import Task
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.session import SessionCreate, SessionResponse
from agentforge.services.audit_service import AuditService

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
audit_service = AuditService()


def to_session_response(
    session: Session,
    *,
    task_count: int = 0,
    tool_call_count: int = 0,
    approval_count: int = 0,
) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
        metadata=session.metadata_json,
        task_count=task_count,
        tool_call_count=tool_call_count,
        approval_count=approval_count,
    )


async def get_session_or_404(db: AsyncSession, session_id: UUID) -> Session:
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


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    body: SessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    session = Session(
        user_id=request.state.user_id,
        status=SessionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        metadata_json=body.metadata,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    await audit_service.record_event(
        db,
        event_type="session.started",
        actor=request.state.user_id,
        payload={
            "session_id": str(session.id),
            "status": session.status.value,
            "metadata": session.metadata_json,
        },
        session_id=session.id,
    )

    return to_session_response(session)


@router.get("", response_model=Envelope[SessionResponse])
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    status_filter: SessionStatus | None = Query(default=None, alias="status"),
) -> Envelope[SessionResponse]:
    query = select(Session)
    count_query = select(func.count()).select_from(Session)

    if status_filter is not None:
        query = query.where(Session.status == status_filter)
        count_query = count_query.where(Session.status == status_filter)

    total = int((await db.execute(count_query)).scalar_one())
    sessions = list(
        (
            await db.execute(
                query.order_by(Session.started_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )

    return Envelope(
        data=[to_session_response(session) for session in sessions],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    session = await get_session_or_404(db, session_id)
    task_count = int(
        (
            await db.execute(
                select(func.count()).select_from(Task).where(Task.session_id == session_id),
            )
        ).scalar_one()
    )
    return to_session_response(session, task_count=task_count)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    session = await get_session_or_404(db, session_id)
    if session.ended_at is not None or session.status != SessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": "Session has already ended",
                "detail": {"session_id": str(session_id)},
            },
        )

    session.status = SessionStatus.COMPLETED
    session.ended_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)

    await audit_service.record_event(
        db,
        event_type="session.ended",
        actor=request.state.user_id,
        payload={
            "session_id": str(session.id),
            "status": session.status.value,
            "ended_at": session.ended_at.isoformat(),
        },
        session_id=session.id,
    )

    task_count = int(
        (
            await db.execute(
                select(func.count()).select_from(Task).where(Task.session_id == session_id),
            )
        ).scalar_one()
    )
    return to_session_response(session, task_count=task_count)
