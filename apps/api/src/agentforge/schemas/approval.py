from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from agentforge.models.approval import ApprovalDecision, RiskLevel


class ApprovalResponse(BaseModel):
    id: UUID
    task_id: UUID
    task_step_id: UUID | None
    risk_level: RiskLevel
    risk_reason: str
    action_summary: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision: ApprovalDecision
    rationale: str | None

    model_config = ConfigDict(from_attributes=True)


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    rationale: str | None = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: ApprovalDecision) -> ApprovalDecision:
        if value == ApprovalDecision.PENDING:
            raise ValueError("Decision must be approved or rejected")
        return value
