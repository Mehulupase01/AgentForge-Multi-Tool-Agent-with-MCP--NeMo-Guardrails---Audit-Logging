from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.auth import require_api_key
from agentforge.database import get_db
from agentforge.models.trigger import Trigger, TriggerEvent, TriggerSource
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.trigger import (
    TriggerCreate,
    TriggerEventResponse,
    TriggerResponse,
    TriggerUpdate,
    TriggerWebhookResponse,
)
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.trigger_service import TriggerProcessResult, TriggerService, get_trigger_service
from agentforge.routers.tasks import orchestrator_dependency

router = APIRouter(prefix="/api/v1/triggers", tags=["triggers"])


def to_trigger_response(trigger: Trigger) -> TriggerResponse:
    return TriggerResponse(
        id=trigger.id,
        name=trigger.name,
        source=trigger.source,
        config=trigger.config_json,
        prompt_template=trigger.prompt_template,
        status=trigger.status,
        last_fired_at=trigger.last_fired_at,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
    )


def to_trigger_event_response(event: TriggerEvent) -> TriggerEventResponse:
    return TriggerEventResponse(
        id=event.id,
        trigger_id=event.trigger_id,
        source_headers_json=event.source_headers_json,
        payload_json=event.payload_json,
        signature_valid=event.signature_valid,
        status=event.status,
        received_at=event.received_at,
        processed_at=event.processed_at,
        resulting_task_id=event.resulting_task_id,
        rejection_reason=event.rejection_reason,
    )


@router.post("", response_model=TriggerResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
async def create_trigger(
    body: TriggerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
) -> TriggerResponse:
    trigger = await trigger_service.create_trigger(
        db,
        name=body.name,
        source=body.source,
        config=body.config,
        prompt_template=body.prompt_template,
        secret=body.secret,
        status=body.status,
    )
    return to_trigger_response(trigger)


@router.get("", response_model=Envelope[TriggerResponse], dependencies=[Depends(require_api_key)])
async def list_triggers(
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[TriggerResponse]:
    total = int((await db.execute(select(func.count()).select_from(Trigger))).scalar_one())
    triggers = await trigger_service.list_triggers(db)
    page_items = triggers[(page - 1) * per_page : page * per_page]
    return Envelope(
        data=[to_trigger_response(trigger) for trigger in page_items],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/{trigger_id}", response_model=TriggerResponse, dependencies=[Depends(require_api_key)])
async def get_trigger(
    trigger_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
) -> TriggerResponse:
    trigger = await trigger_service.get_trigger(db, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return to_trigger_response(trigger)


@router.patch("/{trigger_id}", response_model=TriggerResponse, dependencies=[Depends(require_api_key)])
async def update_trigger(
    trigger_id: UUID,
    body: TriggerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
) -> TriggerResponse:
    trigger = await trigger_service.get_trigger(db, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    updated = await trigger_service.update_trigger(
        db,
        trigger,
        name=body.name,
        config_json=body.config,
        prompt_template=body.prompt_template,
        secret=body.secret,
        status=body.status,
    )
    return to_trigger_response(updated)


@router.delete("/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_api_key)])
async def delete_trigger(
    trigger_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
) -> Response:
    trigger = await trigger_service.get_trigger(db, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    await trigger_service.delete_trigger(db, trigger)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{trigger_id}/events", response_model=Envelope[TriggerEventResponse], dependencies=[Depends(require_api_key)])
async def list_trigger_events(
    trigger_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[TriggerEventResponse]:
    trigger = await trigger_service.get_trigger(db, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    total = int((await db.execute(select(func.count()).select_from(TriggerEvent).where(TriggerEvent.trigger_id == trigger_id))).scalar_one())
    events = await trigger_service.list_events(db, trigger_id)
    page_items = events[(page - 1) * per_page : page * per_page]
    return Envelope(
        data=[to_trigger_event_response(event) for event in page_items],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.post("/webhook/{source}", response_model=TriggerWebhookResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_webhook(
    source: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
) -> TriggerWebhookResponse:
    source_map = {
        "github": TriggerSource.GITHUB_WEBHOOK,
        "generic": TriggerSource.GENERIC_WEBHOOK,
    }
    if source not in source_map:
        raise HTTPException(status_code=404, detail="Unsupported trigger source")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    try:
        result = await trigger_service.process_webhook(
            db,
            source=source_map[source],
            headers=dict(request.headers),
            raw_body=raw_body,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not result.accepted:
        if result.trigger_event.rejection_reason == "invalid_signature":
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "UNAUTHENTICATED",
                    "message": "Webhook signature validation failed",
                    "detail": {"trigger_event_id": str(result.trigger_event.id)},
                },
            )
        if result.trigger_event.rejection_reason == "trigger_disabled":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONFLICT",
                    "message": "Trigger is disabled",
                    "detail": {"trigger_event_id": str(result.trigger_event.id)},
                },
            )

    if result.task is not None:
        orchestrator.start_task(result.task.id)

    return TriggerWebhookResponse(
        trigger_event_id=result.trigger_event.id,
        accepted=result.accepted,
        task_id=result.task.id if result.task is not None else None,
    )


@router.post("/internal/fire", response_model=TriggerWebhookResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_api_key)])
async def trigger_internal_fire(
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_service: Annotated[TriggerService, Depends(get_trigger_service)],
    orchestrator: Annotated[AgentOrchestrator, Depends(orchestrator_dependency)],
    body: dict = Body(...),
) -> TriggerWebhookResponse:
    trigger_id = body.get("trigger_id")
    if not trigger_id:
        raise HTTPException(status_code=400, detail="trigger_id is required")
    try:
        result = await trigger_service.fire_internal_schedule(db, trigger_id=UUID(str(trigger_id)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not result.accepted and result.trigger_event.rejection_reason == "trigger_disabled":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFLICT",
                "message": "Trigger is disabled",
                "detail": {"trigger_event_id": str(result.trigger_event.id)},
            },
        )

    if result.task is not None:
        orchestrator.start_task(result.task.id)

    return TriggerWebhookResponse(
        trigger_event_id=result.trigger_event.id,
        accepted=result.accepted,
        task_id=result.task.id if result.task is not None else None,
    )
