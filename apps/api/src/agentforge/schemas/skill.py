from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from agentforge.models.agent_run import AgentRole


class SkillResponse(BaseModel):
    id: UUID
    name: str
    version: str
    description: str
    agent_role: AgentRole
    tools: list[str]
    knowledge_refs: list[str]
    policy: dict
    source_path: str
    content_hash: str
    registered_at: datetime


class SkillInvocationResponse(BaseModel):
    id: UUID
    skill_id: UUID
    task_step_id: UUID
    policy_checks_json: dict
    injected_knowledge_tokens: int
    invoked_at: datetime


class SkillReloadResponse(BaseModel):
    loaded: int
    updated: int
    removed: int
