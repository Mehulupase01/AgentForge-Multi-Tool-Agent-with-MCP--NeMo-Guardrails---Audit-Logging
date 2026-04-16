from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from agentforge.models.session import SessionStatus


class SessionCreate(BaseModel):
    metadata: dict = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: UUID
    user_id: str
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)
    task_count: int = 0
    tool_call_count: int = 0
    approval_count: int = 0
