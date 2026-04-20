from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
import yaml

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.models.agent_run import AgentRole, AgentRun
from agentforge.models.approval import Approval, ApprovalDecision
from agentforge.models.audit_event import AuditEvent
from agentforge.models.task_step import TaskStep
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 8
        self.completion_tokens = 12
        self.latency_ms = 1


class MultiAgentLLMProvider:
    provider_name = "mock"
    model_name = "mock-multi-agent"

    def __init__(self) -> None:
        self.plan_text = json.dumps(
            {
                "handoffs": [
                    {
                        "to": "researcher",
                        "reason": "Find AI articles from the corpus.",
                        "payload": {"query": "AI", "limit": 3, "description": "Search the corpus for AI articles."},
                    },
                    {
                        "to": "analyst",
                        "reason": "List engineers from the workforce database.",
                        "payload": {"department": "Engineering", "limit": 3, "description": "List engineering employees."},
                    },
                ]
            }
        )

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        raise AssertionError("Phase 11 multi-agent path should not call generate_plan for this prompt.")

    async def generate_supervisor_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def compose_multi_agent_summary(self, user_prompt: str, specialist_results: list[dict]) -> str:
        summaries = [item["summary"] for item in specialist_results]
        return " ".join(summaries)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse("unused")


class OutOfScopeLLMProvider(MultiAgentLLMProvider):
    def __init__(self) -> None:
        self.plan_text = json.dumps(
            {
                "handoffs": [
                    {
                        "to": "analyst",
                        "reason": "Attempt an illegal github call from the analyst role.",
                        "payload": {
                            "server": "github",
                            "tool": "list_user_repos",
                            "args": {"username": "openai", "limit": 3},
                            "description": "Illegal analyst GitHub lookup.",
                        },
                    }
                ]
            }
        )


class FakeMCPPool:
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        if (server_name, tool_name) == ("file_search", "search_corpus"):
            return [
                {"filename": "01-transformer-architectures-in-practice.md", "title": "Transformers", "score": 9},
                {"filename": "30-open-source-foundation-models.md", "title": "Open Models", "score": 7},
            ]
        if (server_name, tool_name) == ("sqlite_query", "list_employees"):
            return [
                {"employee_id": 1, "name": "Ava", "department": "Engineering"},
                {"employee_id": 2, "name": "Milo", "department": "Engineering"},
            ]
        raise KeyError((server_name, tool_name))


class FlakySupervisorMCPPool(FakeMCPPool):
    def __init__(self, *, fail_count: int) -> None:
        self.fail_count = fail_count
        self.calls = 0

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        if (server_name, tool_name) == ("file_search", "search_corpus"):
            self.calls += 1
            if self.calls <= self.fail_count:
                raise httpx.TimeoutException("research corpus fetch timed out")
        return await super().call_tool(server_name, tool_name, arguments)


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


async def wait_for_status(client: AsyncClient, task_id: str, *terminal_statuses: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        payload = response.json()
        if payload["status"] in terminal_statuses:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {terminal_statuses}")


@pytest_asyncio.fixture
async def guardrails_runner(tmp_path: Path) -> GuardrailsRunner:
    return GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "tool_allowlist.yml")))


@pytest_asyncio.fixture
async def approval_service() -> ApprovalService:
    return ApprovalService()


def build_orchestrator(
    session_factory,
    guardrails_runner: GuardrailsRunner,
    approval_service: ApprovalService,
    tmp_path: Path,
    provider,
    *,
    mcp_pool=None,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=mcp_pool or FakeMCPPool(),
        llm_provider=provider,
        event_bus=TaskEventBus(),
        guardrails_runner=guardrails_runner,
        approval_service=approval_service,
        audit_service=AuditService(),
        checkpoint_path=str(tmp_path / "orchestrator_checkpoints.sqlite"),
    )


@pytest_asyncio.fixture
async def supervisor_app(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path):
    orchestrator = build_orchestrator(session_factory, guardrails_runner, approval_service, tmp_path, MultiAgentLLMProvider())
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner
    yield app
    await orchestrator.close()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def supervisor_client(supervisor_app):
    async with AsyncClient(
        transport=ASGITransport(app=supervisor_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_supervisor_routes_two_specialists(supervisor_client: AsyncClient, session_factory) -> None:
    session_response = await supervisor_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]

    create_response = await supervisor_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Find 3 AI articles and list 3 engineers."},
    )
    task_id = create_response.json()["id"]

    payload = await wait_for_status(supervisor_client, task_id, "completed")
    assert "Researcher found" in payload["final_response"]
    assert "Analyst returned" in payload["final_response"]

    agents_response = await supervisor_client.get(f"/api/v1/tasks/{task_id}/agents")
    assert agents_response.status_code == 200
    roles = [item["role"] for item in agents_response.json()["data"]]
    assert roles.count("researcher") == 1
    assert roles.count("analyst") == 1

    async with session_factory() as session:
        specialist_runs = list(
            (
                await session.execute(
                    select(AgentRun).where(AgentRun.task_id == UUID(task_id), AgentRun.role != AgentRole.ORCHESTRATOR),
                )
            ).scalars()
        )
    assert len(specialist_runs) == 2


async def test_specialist_cannot_call_out_of_scope_tool(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(session_factory, guardrails_runner, approval_service, tmp_path, OutOfScopeLLMProvider())
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        session_response = await client.post("/api/v1/sessions", json={})
        session_id = session_response.json()["id"]
        create_response = await client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": "List GitHub repos and employees in one response."},
        )
        task_id = create_response.json()["id"]
        payload = await wait_for_status(client, task_id, "rejected")
        assert "outside the analyst scope" in payload["error"]

    async with session_factory() as session:
        events = list((await session.execute(select(AuditEvent).where(AuditEvent.event_type == "guardrail.tool_disallowed"))).scalars())
        runs = list((await session.execute(select(AgentRun).where(AgentRun.task_id == UUID(task_id)))).scalars())
        steps = list((await session.execute(select(TaskStep).where(TaskStep.task_id == UUID(task_id)))).scalars())

    assert events
    assert any(run.status.value == "rejected" for run in runs if run.role == AgentRole.ANALYST)
    assert any(step.agent_run_id is not None for step in steps)

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_agent_runs_linked_to_task_steps(supervisor_client: AsyncClient, session_factory) -> None:
    session_response = await supervisor_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]
    create_response = await supervisor_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Find 3 AI articles and list 3 engineers."},
    )
    task_id = create_response.json()["id"]

    await wait_for_status(supervisor_client, task_id, "completed")

    async with session_factory() as session:
        runs = list((await session.execute(select(AgentRun).where(AgentRun.task_id == UUID(task_id)))).scalars())
        run_ids = {run.id for run in runs if run.role != AgentRole.ORCHESTRATOR}
        linked_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(TaskStep).where(TaskStep.task_id == UUID(task_id), TaskStep.agent_run_id.in_(run_ids)),
                )
            ).scalar_one()
        )
    assert run_ids
    assert linked_count >= len(run_ids)


async def test_supervisor_retries_specialist_tool_call(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(
        session_factory,
        guardrails_runner,
        approval_service,
        tmp_path,
        MultiAgentLLMProvider(),
        mcp_pool=FlakySupervisorMCPPool(fail_count=1),
    )
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        session_response = await client.post("/api/v1/sessions", json={})
        session_id = session_response.json()["id"]
        create_response = await client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": "Find 3 AI articles and list 3 engineers."},
        )
        task_id = create_response.json()["id"]
        payload = await wait_for_status(client, task_id, "completed")
        assert payload["status"] == "completed"

    async with session_factory() as session:
        steps = list((await session.execute(select(TaskStep).where(TaskStep.task_id == UUID(task_id)).order_by(TaskStep.ordinal.asc()))).scalars())
        events = list((await session.execute(select(AuditEvent).where(AuditEvent.event_type == "agent.retry"))).scalars())

    assert any(step.agent_role == AgentRole.RESEARCHER and step.step_type.value == "reflection" for step in steps)
    assert any(step.agent_role == AgentRole.RESEARCHER and step.step_type.value == "retry" for step in steps)
    assert any(event.payload_json.get("role") == AgentRole.RESEARCHER.value for event in events)

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_supervisor_resume_after_retry_escalation(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(
        session_factory,
        guardrails_runner,
        approval_service,
        tmp_path,
        MultiAgentLLMProvider(),
        mcp_pool=FlakySupervisorMCPPool(fail_count=3),
    )
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        session_response = await client.post("/api/v1/sessions", json={})
        session_id = session_response.json()["id"]
        create_response = await client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": "Find 3 AI articles and list 3 engineers."},
        )
        task_id = create_response.json()["id"]
        payload = await wait_for_status(client, task_id, "awaiting_approval")
        assert payload["status"] == "awaiting_approval"

        async with session_factory() as session:
            approval_row = (
                await session.execute(
                    select(Approval)
                    .where(Approval.task_id == UUID(task_id))
                    .order_by(Approval.requested_at.desc())
                )
            ).scalars().first()
        assert approval_row is not None

        decision_response = await client.post(
            f"/api/v1/approvals/{approval_row.id}/decision",
            json={"decision": ApprovalDecision.APPROVED.value, "rationale": "Retry with the same read-only tool."},
        )
        assert decision_response.status_code == 200

        resume_response = await client.post(f"/api/v1/tasks/{task_id}/resume")
        assert resume_response.status_code == 200
        payload = await wait_for_status(client, task_id, "completed")
        assert payload["status"] == "completed"

    await orchestrator.close()
    app.dependency_overrides.clear()
