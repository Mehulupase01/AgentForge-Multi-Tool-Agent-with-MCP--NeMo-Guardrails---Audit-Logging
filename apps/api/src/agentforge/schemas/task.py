from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from agentforge.schemas.agent import AgentRunSummary
from agentforge.models.agent_run import AgentRole
from agentforge.models.task import TaskStatus
from agentforge.models.task_step import StepStatus, StepType


class TaskCreate(BaseModel):
    user_prompt: str = Field(min_length=1)


class ReplayRequest(BaseModel):
    from_checkpoint: str | None = None


class PlanStep(BaseModel):
    step_id: str
    type: Literal["tool_call", "llm_reasoning", "approval_gate"]
    description: str
    server: str | None = None
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_fields(self) -> "PlanStep":
        if self.type == "tool_call":
            if not self.server or not self.tool:
                raise ValueError("tool_call steps require both server and tool")
            return self

        self.server = None
        self.tool = None
        return self


class TaskResponse(BaseModel):
    id: UUID
    session_id: UUID
    user_prompt: str
    plan: list[PlanStep] | None = None
    supervisor_plan: dict[str, Any] | None = None
    status: TaskStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    final_response: str | None = None
    error: str | None = None
    checkpoint_id: str | None = None
    agent_runs: list[AgentRunSummary] = Field(default_factory=list)


class ReplayResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    skipped_completed_steps: int = 0
    approval_id: UUID | None = None


class TaskStepResponse(BaseModel):
    id: UUID
    task_id: UUID
    ordinal: int
    step_type: StepType
    description: str
    status: StepStatus
    agent_role: AgentRole
    attempt: int
    parent_step_id: UUID | None = None
    agent_run_id: UUID | None = None
    input_json: Any | None = None
    output_json: Any | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
