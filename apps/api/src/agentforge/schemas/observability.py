from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CostByAgent(BaseModel):
    role: str
    prompt_tokens: int
    completion_tokens: int
    usd: float


class TaskCostResponse(BaseModel):
    task_id: UUID
    by_agent: list[CostByAgent]
    total_usd: float


class StepConfidenceResponse(BaseModel):
    step_id: UUID
    value: float
    heuristic_value: float
    self_reported_value: float | None = None
    factors: dict


class TaskConfidenceResponse(BaseModel):
    task_id: UUID
    task_confidence: float | None = None
    heuristic_value: float | None = None
    self_reported_value: float | None = None
    steps: list[StepConfidenceResponse]


class SummaryByAgent(BaseModel):
    role: str
    tasks: int
    usd: float


class ObservabilitySummaryResponse(BaseModel):
    tasks: int
    total_usd: float
    avg_confidence: float
    retry_rate: float
    by_agent: list[SummaryByAgent]


class AgentHandoffEdge(BaseModel):
    from_role: str
    to_role: str
    count: int

    @classmethod
    def from_payload(cls, payload: dict) -> "AgentHandoffEdge":
        return cls(from_role=payload["from"], to_role=payload["to"], count=payload["count"])


class AgentHandoffsResponse(BaseModel):
    edges: list[AgentHandoffEdge]
