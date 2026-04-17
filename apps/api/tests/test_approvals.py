from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.models.approval import Approval, ApprovalDecision, RiskLevel
from agentforge.models.audit_event import AuditEvent
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService, get_approval_service
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 8
        self.completion_tokens = 16
        self.latency_ms = 1


class ApprovalLLMProvider:
    provider_name = "mock"
    model_name = "mock-approval-model"

    def __init__(self) -> None:
        self.plan_text = self.medium_plan()

    @staticmethod
    def medium_plan() -> str:
        return json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "type": "tool_call",
                        "description": "Fetch the external report.",
                        "server": "web_fetch",
                        "tool": "fetch_url",
                        "args": {"url": "https://unsafe.example.org/report"},
                    },
                    {
                        "step_id": "step-2",
                        "type": "llm_reasoning",
                        "description": "Summarize the fetched report.",
                        "args": {},
                    },
                ]
            }
        )

    @staticmethod
    def low_risk_plan() -> str:
        return json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "type": "tool_call",
                        "description": "Search the corpus for transformers.",
                        "server": "file_search",
                        "tool": "search_corpus",
                        "args": {"query": "transformer", "limit": 2},
                    },
                    {
                        "step_id": "step-2",
                        "type": "llm_reasoning",
                        "description": "Summarize the corpus search results.",
                        "args": {},
                    },
                ]
            }
        )

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse("The fetched content was summarized successfully.")


class FakeApprovalMCPPool:
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        if (server_name, tool_name) == ("web_fetch", "fetch_url"):
            return {"url": arguments["url"], "status_code": 200, "content": "External report content"}
        if (server_name, tool_name) == ("file_search", "search_corpus"):
            return [{"filename": "transformers-overview.md", "snippet": "Transformers...", "score": 9}]
        raise KeyError((server_name, tool_name))


def write_allowlist(path: Path) -> Path:
    payload = {
        "allowlist": {
            "file_search": ["search_corpus", "read_document"],
            "web_fetch": ["fetch_url", "hacker_news_top", "weather_for"],
            "sqlite_query": ["list_employees", "list_projects", "run_select"],
            "github": ["list_user_repos", "search_issues", "get_repo"],
        }
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


async def wait_for_status(client: AsyncClient, task_id: str, *statuses: str) -> dict:
    await asyncio.sleep(0.5)
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {statuses}")


async def wait_for_approval(session_factory, task_id: str) -> Approval:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            approval = (
                await session.execute(
                    select(Approval).where(Approval.task_id == UUID(task_id)).order_by(Approval.requested_at.desc()),
                )
            ).scalars().first()
        if approval is not None:
            return approval
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for approval on task {task_id}")


async def wait_for_audit_events(session_factory, *event_types: str) -> list[AuditEvent]:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            events = list(
                (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.event_type.in_(event_types)).order_by(AuditEvent.sequence.asc()),
                    )
                ).scalars()
            )
        if {event.event_type for event in events} >= set(event_types):
            return events
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for audit events {event_types}")


async def create_session_and_task(client: AsyncClient, prompt: str) -> tuple[str, str]:
    session_response = await client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]
    task_response = await client.post(f"/api/v1/sessions/{session_id}/tasks", json={"user_prompt": prompt})
    return session_id, task_response.json()["id"]


@pytest_asyncio.fixture
async def guardrails_runner(tmp_path: Path) -> GuardrailsRunner:
    return GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "tool_allowlist.yml")))


@pytest_asyncio.fixture
async def approval_service() -> ApprovalService:
    return ApprovalService()


@pytest_asyncio.fixture
async def llm_provider() -> ApprovalLLMProvider:
    return ApprovalLLMProvider()


@pytest_asyncio.fixture
async def approval_app(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, llm_provider: ApprovalLLMProvider, tmp_path: Path):
    event_bus = TaskEventBus()
    orchestrator = AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=FakeApprovalMCPPool(),
        llm_provider=llm_provider,
        event_bus=event_bus,
        guardrails_runner=guardrails_runner,
        approval_service=approval_service,
        audit_service=AuditService(),
        checkpoint_path=str(tmp_path / "approval_checkpoints.sqlite"),
    )
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: event_bus
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner
    app.dependency_overrides[get_approval_service] = lambda: approval_service
    yield app
    await orchestrator.close()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def approval_client(approval_app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=approval_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_get_pending_approvals(approval_client: AsyncClient, session_factory, llm_provider: ApprovalLLMProvider) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    response = await approval_client.get("/api/v1/approvals", params={"decision": "pending"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]
    assert payload["data"][0]["id"] == str(approval.id)


async def test_post_decision_approves_and_resumes(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Open the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    response = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "rationale": "Reviewed and approved."},
    )

    assert response.status_code == 200
    task_payload = await wait_for_status(approval_client, task_id, "completed")
    assert task_payload["status"] == "completed"
    assert task_payload["final_response"]


async def test_post_decision_rejects_task(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    response = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "rejected", "rationale": "Do not contact untrusted hosts."},
    )

    assert response.status_code == 200
    task_payload = await wait_for_status(approval_client, task_id, "rejected")
    assert task_payload["status"] == "rejected"

    async with session_factory() as session:
        gate_step = (
            await session.execute(
                select(TaskStep)
                .where(TaskStep.task_id == UUID(task_id), TaskStep.step_type == StepType.APPROVAL_GATE)
                .order_by(TaskStep.ordinal.asc()),
            )
        ).scalars().first()

    assert gate_step is not None
    assert gate_step.status == StepStatus.FAILED


async def test_decision_idempotency(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    first = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "rationale": "Approved once."},
    )
    second = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "rejected", "rationale": "Trying again."},
    )

    assert first.status_code == 200
    assert second.status_code == 409


async def test_medium_risk_created_for_disallowed_host(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    task_payload = await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    assert task_payload["status"] == "awaiting_approval"
    assert approval.decision == ApprovalDecision.PENDING
    assert approval.risk_level == RiskLevel.MEDIUM


async def test_low_risk_tool_skips_queue(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.low_risk_plan()
    _, task_id = await create_session_and_task(approval_client, "Search the corpus and summarize transformers.")
    task_payload = await wait_for_status(approval_client, task_id, "completed")

    assert task_payload["status"] == "completed"
    async with session_factory() as session:
        approval = (
            await session.execute(
                select(Approval).where(Approval.task_id == UUID(task_id)),
            )
        ).scalars().first()

    assert approval is None


async def test_audit_records_approval_lifecycle(
    approval_client: AsyncClient,
    session_factory,
    llm_provider: ApprovalLLMProvider,
) -> None:
    llm_provider.plan_text = ApprovalLLMProvider.medium_plan()
    _, task_id = await create_session_and_task(approval_client, "Fetch the external report and summarize it.")
    await wait_for_status(approval_client, task_id, "awaiting_approval")
    approval = await wait_for_approval(session_factory, task_id)

    response = await approval_client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approved", "rationale": "Audited decision."},
    )

    assert response.status_code == 200
    events = await wait_for_audit_events(session_factory, "approval.requested", "approval.decided")
    event_types = [event.event_type for event in events]
    assert "approval.requested" in event_types
    assert "approval.decided" in event_types
