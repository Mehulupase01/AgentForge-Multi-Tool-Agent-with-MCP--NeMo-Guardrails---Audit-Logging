from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    sequence: int
    session_id: UUID | None = None
    task_id: UUID | None = None
    event_type: str
    actor: str
    payload: dict
    payload_hash: str
    prev_hash: str | None = None
    chain_hash: str
    created_at: datetime


class IntegrityResponse(BaseModel):
    verified: bool
    events_checked: int
    first_broken_sequence: int | None = None
    expected_chain_hash: str | None = None
    actual_chain_hash: str | None = None
