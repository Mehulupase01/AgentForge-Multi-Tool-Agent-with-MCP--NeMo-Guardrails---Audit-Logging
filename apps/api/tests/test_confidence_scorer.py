from __future__ import annotations

import pytest

from agentforge.services.approval_service import ApprovalService
from agentforge.services.confidence_scorer import ConfidenceScorer


class NoopConfidenceProvider:
    provider_name = "mock"
    model_name = "mock-confidence"


@pytest.mark.asyncio
async def test_confidence_heuristic_components() -> None:
    scorer = ConfidenceScorer(
        approval_service=ApprovalService(),
        llm_provider=NoopConfidenceProvider(),
    )

    heuristic = scorer.heuristic_from_factors(
        retry_count=2,
        guardrail_block_count=1,
        review_flagged_count=0,
        review_rejected_count_recovered=0,
        successful_skill_policy_checks=0,
    )

    assert heuristic == 60


@pytest.mark.asyncio
async def test_confidence_merges_self_report() -> None:
    scorer = ConfidenceScorer(
        approval_service=ApprovalService(),
        llm_provider=NoopConfidenceProvider(),
    )

    assert scorer.merge_with_self_report(60, 90) == 72
