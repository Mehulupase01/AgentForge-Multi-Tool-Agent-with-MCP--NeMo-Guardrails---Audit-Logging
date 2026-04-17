from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db, get_session_factory
from agentforge.models.redteam import RedteamCategory, RedteamResult, RedteamRun
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.redteam import RedteamResultResponse, RedteamRunRequest, RedteamRunResponse
from agentforge.services.redteam_service import RedteamRunner, get_redteam_runner

router = APIRouter(prefix="/api/v1/redteam", tags=["redteam"])


def redteam_runner_dependency() -> RedteamRunner:
    return get_redteam_runner(session_factory=get_session_factory())


async def get_run_or_404(db: AsyncSession, run_id: UUID) -> RedteamRun:
    run = await db.get(RedteamRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Redteam run not found",
                "detail": {"run_id": str(run_id)},
            },
        )
    return run


@router.post("/run", response_model=RedteamRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_redteam_run(
    body: RedteamRunRequest,
    runner: Annotated[RedteamRunner, Depends(redteam_runner_dependency)],
) -> RedteamRunResponse:
    run = await runner.start_background_run(body.scenario_ids)
    return RedteamRunResponse.model_validate(run)


@router.get("/runs", response_model=Envelope[RedteamRunResponse])
async def list_redteam_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[RedteamRunResponse]:
    total = int((await db.execute(select(func.count()).select_from(RedteamRun))).scalar_one())
    runs = list(
        (
            await db.execute(
                select(RedteamRun)
                .order_by(RedteamRun.started_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page),
            )
        ).scalars()
    )
    return Envelope(
        data=[RedteamRunResponse.model_validate(run) for run in runs],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/runs/{run_id}", response_model=RedteamRunResponse)
async def get_redteam_run(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedteamRunResponse:
    run = await get_run_or_404(db, run_id)
    return RedteamRunResponse.model_validate(run)


@router.get("/runs/{run_id}/results", response_model=Envelope[RedteamResultResponse])
async def list_redteam_results(
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    passed: bool | None = Query(default=None),
    category: RedteamCategory | None = Query(default=None),
) -> Envelope[RedteamResultResponse]:
    await get_run_or_404(db, run_id)

    query = select(RedteamResult).where(RedteamResult.run_id == run_id)
    count_query = select(func.count()).select_from(RedteamResult).where(RedteamResult.run_id == run_id)

    if passed is not None:
        query = query.where(RedteamResult.passed == passed)
        count_query = count_query.where(RedteamResult.passed == passed)
    if category is not None:
        query = query.where(RedteamResult.category == category)
        count_query = count_query.where(RedteamResult.category == category)

    total = int((await db.execute(count_query)).scalar_one())
    results = list(
        (
            await db.execute(
                query.order_by(RedteamResult.scenario_id.asc()).offset((page - 1) * per_page).limit(per_page),
            )
        ).scalars()
    )
    return Envelope(
        data=[RedteamResultResponse.model_validate(result) for result in results],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )
