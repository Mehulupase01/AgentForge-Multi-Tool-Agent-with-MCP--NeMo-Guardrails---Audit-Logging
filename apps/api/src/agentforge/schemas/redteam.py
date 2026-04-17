from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentforge.models.redteam import RedteamCategory, RedteamOutcome


class RedteamRunRequest(BaseModel):
    scenario_ids: list[str] | None = None


class RedteamRunResponse(BaseModel):
    id: UUID
    started_at: datetime
    completed_at: datetime | None
    commit_sha: str | None
    total_scenarios: int
    passed: int
    failed: int
    safety_compliance_pct: float

    model_config = ConfigDict(from_attributes=True)


class RedteamResultResponse(BaseModel):
    id: UUID
    run_id: UUID
    scenario_id: str
    category: RedteamCategory
    prompt: str
    expected_outcome: RedteamOutcome
    actual_outcome: RedteamOutcome
    passed: bool
    details_json: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)
