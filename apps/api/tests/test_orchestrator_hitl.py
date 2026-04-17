from __future__ import annotations

import asyncio

from httpx import AsyncClient

from .test_approvals import (
    ApprovalLLMProvider,
    approval_app,
    approval_client,
    approval_service,
    create_session_and_task,
    guardrails_runner,
    llm_provider,
    wait_for_approval,
    wait_for_status,
)


async def test_orchestrator_hitl_resume_endpoint(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    decision_response = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "rationale": "Safe to continue."},
    )
    resume_response = await approval_client.post(f"/api/v1/tasks/{task_id}/resume")

    assert decision_response.status_code == 200
    assert resume_response.status_code == 200

    task_payload = await wait_for_status(approval_client, task_id, "completed")
    assert task_payload["status"] == "completed"
