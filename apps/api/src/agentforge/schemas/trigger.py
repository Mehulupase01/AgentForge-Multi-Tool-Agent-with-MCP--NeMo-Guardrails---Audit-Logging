from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentforge.models.trigger import TriggerEventStatus, TriggerSource, TriggerStatus


class TriggerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source: TriggerSource
    config: dict = Field(default_factory=dict)
    prompt_template: str = Field(min_length=1)
    secret: str | None = None
    status: TriggerStatus = TriggerStatus.ENABLED


class TriggerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict | None = None
    prompt_template: str | None = Field(default=None, min_length=1)
    secret: str | None = None
    status: TriggerStatus | None = None


class TriggerResponse(BaseModel):
    id: UUID
    name: str
    source: TriggerSource
    config: dict
    prompt_template: str
    status: TriggerStatus
    last_fired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TriggerEventSummary(BaseModel):
    id: UUID
    trigger_id: UUID
    signature_valid: bool
    status: TriggerEventStatus
    received_at: datetime
    processed_at: datetime | None = None
    resulting_task_id: UUID | None = None
    rejection_reason: str | None = None


class TriggerEventResponse(TriggerEventSummary):
    source_headers_json: dict | None = None
    payload_json: dict


class TriggerWebhookResponse(BaseModel):
    trigger_event_id: UUID
    accepted: bool
    task_id: UUID | None = None
