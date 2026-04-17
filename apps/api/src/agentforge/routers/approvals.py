from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db
from agentforge.models.approval import Approval, ApprovalDecision
from agentforge.schemas.approval import ApprovalDecisionRequest, ApprovalResponse
from agentforge.schemas.common import Envelope, Pagination
from agentforge.services.approval_service import ApprovalService, get_approval_service

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


async def get_approval_or_404(db: AsyncSession, approval_id: UUID) -> Approval:
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Approval not found",
                "detail": {"approval_id": str(approval_id)},
            },
        )
    return approval


@router.get("", response_model=Envelope[ApprovalResponse])
async def list_approvals(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    decision: ApprovalDecision | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
) -> Envelope[ApprovalResponse]:
    query = select(Approval)
    count_query = select(func.count()).select_from(Approval)

    if decision is not None:
        query = query.where(Approval.decision == decision)
        count_query = count_query.where(Approval.decision == decision)
    if task_id is not None:
        query = query.where(Approval.task_id == task_id)
        count_query = count_query.where(Approval.task_id == task_id)

    total = int((await db.execute(count_query)).scalar_one())
    approvals = list(
        (
            await db.execute(
                query.order_by(Approval.requested_at.desc()).offset((page - 1) * per_page).limit(per_page),
            )
        ).scalars()
    )

    return Envelope(
        data=[ApprovalResponse.model_validate(approval) for approval in approvals],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApprovalResponse:
    approval = await get_approval_or_404(db, approval_id)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    approval_service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> ApprovalResponse:
    approval = await get_approval_or_404(db, approval_id)
    if approval.decision != ApprovalDecision.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": "Approval has already been decided",
                "detail": {"approval_id": str(approval_id), "decision": approval.decision.value},
            },
        )

    approval = await approval_service.decide(
        db,
        approval=approval,
        decision=body.decision,
        rationale=body.rationale,
        decided_by=request.state.user_id,
    )
    await approval_service.signal_resume(approval.task_id, approval.id)
    return ApprovalResponse.model_validate(approval)
