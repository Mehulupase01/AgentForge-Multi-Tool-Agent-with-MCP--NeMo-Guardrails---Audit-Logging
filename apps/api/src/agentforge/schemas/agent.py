from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from agentforge.models.agent_run import AgentRole, AgentRunStatus


class AgentRunSummary(BaseModel):
    id: UUID
    role: AgentRole
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    handoff_reason: str | None = None


class AgentRunResponse(AgentRunSummary):
    task_id: UUID
    parent_run_id: UUID | None = None
    handoff_payload_json: dict | None = None
    result_json: dict | None = None


class AgentRosterItem(BaseModel):
    role: AgentRole
    description: str
    tool_scope: list[str]
    skills: list[str]


class AgentRosterResponse(BaseModel):
    data: list[AgentRosterItem]


class AgentCapabilitiesResponse(BaseModel):
    role: AgentRole
    tools: list[str]
    skills: list[str]
    policy_summary: str
