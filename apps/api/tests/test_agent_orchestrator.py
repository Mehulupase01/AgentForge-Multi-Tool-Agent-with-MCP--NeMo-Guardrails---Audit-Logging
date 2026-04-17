from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from agentforge.database import get_db
from agentforge.main import create_app
from agentforge.models.audit_event import AuditEvent
from agentforge.models.llm_call import LLMCall
from agentforge.models.task_step import TaskStep
from agentforge.models.tool_call import ToolCall
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 12
        self.completion_tokens = 24
        self.latency_ms = 1


class MockLLMProvider:
    provider_name = "mock"
    model_name = "mock-model"

    def __init__(self) -> None:
        self.plan_text = json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "type": "tool_call",
                        "description": "Search the corpus for transformer articles.",
                        "server": "file_search",
                        "tool": "search_corpus",
                        "args": {"query": "transformer", "limit": 3},
                    },
                    {
                        "step_id": "step-2",
                        "type": "tool_call",
                        "description": "Fetch the top Hacker News item.",
                        "server": "web_fetch",
                        "tool": "hacker_news_top",
                        "args": {"count": 1},
                    },
                    {
                        "step_id": "step-3",
                        "type": "llm_reasoning",
                        "description": "Summarize the collected findings.",
                        "args": {},
                    },
                ]
            }
        )

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse("Transformer work is active across the corpus and current news.")


class FakeMCPPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_on: tuple[str, str] | None = None

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        self.calls.append((server_name, tool_name, arguments))
        if self.fail_on == (server_name, tool_name):
            raise RuntimeError(f"{server_name}.{tool_name} failed")

        if (server_name, tool_name) == ("file_search", "search_corpus"):
            return [{"filename": "transformers-overview.md", "snippet": "Transformer architectures...", "score": 7}]
        if (server_name, tool_name) == ("web_fetch", "hacker_news_top"):
            return [{"id": 101, "title": "Transformer Breakthrough", "url": "https://example.com", "score": 99}]
        raise KeyError((server_name, tool_name))


async def wait_for_status(client: AsyncClient, task_id: str, *terminal_statuses: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        payload = response.json()
        if payload["status"] in terminal_statuses:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {terminal_statuses}")


async def wait_for_step_count(client: AsyncClient, task_id: str, expected_count: int) -> list[dict]:
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}/steps")
        payload = response.json()["data"]
        if len(payload) >= expected_count:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to persist {expected_count} steps")


async def wait_for_db_steps(session_factory, task_id: str, expected_count: int) -> list:
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            steps = list(
                (
                    await session.execute(
                        select(TaskStep)
                        .where(TaskStep.task_id == UUID(task_id))
                        .order_by(TaskStep.ordinal.asc()),
                    )
                ).scalars()
            )
        if len(steps) >= expected_count:
            return steps
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to persist {expected_count} TaskStep rows")


async def wait_for_audit_event(session_factory, event_type: str) -> list[AuditEvent]:
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            events = list(
                (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.event_type == event_type),
                    )
                ).scalars()
            )
        if events:
            return events
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for audit event {event_type}")


async def create_session_and_task(client: AsyncClient, prompt: str) -> tuple[str, str]:
    session_response = await client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]
    task_response = await client.post(f"/api/v1/sessions/{session_id}/tasks", json={"user_prompt": prompt})
    return session_id, task_response.json()["id"]


@pytest_asyncio.fixture
async def orchestrator(session_factory) -> AsyncIterator[AgentOrchestrator]:
    event_bus = TaskEventBus()
    fake_pool = FakeMCPPool()
    llm_provider = MockLLMProvider()
    orchestrator = AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=fake_pool,
        llm_provider=llm_provider,
        event_bus=event_bus,
        audit_service=AuditService(),
    )
    orchestrator._fake_pool = fake_pool  # type: ignore[attr-defined]
    orchestrator._event_bus = event_bus
    yield orchestrator
    await orchestrator.close()


@pytest_asyncio.fixture
async def task_app(session_factory, orchestrator: AgentOrchestrator):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def task_client(task_app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=task_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_task_creation_returns_202_planning(task_client: AsyncClient) -> None:
    session_response = await task_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]

    create_response = await task_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Find articles about transformers."},
    )

    assert create_response.status_code == 202
    task_id = create_response.json()["id"]

    get_response = await task_client.get(f"/api/v1/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "planning"


async def test_orchestrator_plans_and_executes_with_mock_llm(
    task_client: AsyncClient,
    session_factory,
) -> None:
    _, task_id = await create_session_and_task(
        task_client,
        "Find three transformer references and summarize them.",
    )

    task_payload = await wait_for_status(task_client, task_id, "completed")
    assert task_payload["final_response"]

    steps = await wait_for_db_steps(session_factory, task_id, 3)
    assert [step.ordinal for step in steps] == [1, 2, 3]
    assert [step.status.value for step in steps] == ["completed", "completed", "completed"]

    async with session_factory() as session:
        tool_call_count = int((await session.execute(select(func.count()).select_from(ToolCall))).scalar_one())
        llm_call_count = int((await session.execute(select(func.count()).select_from(LLMCall))).scalar_one())

    assert tool_call_count == 2
    assert llm_call_count >= 2


async def test_sse_stream_emits_events_in_order(task_client: AsyncClient) -> None:
    session_response = await task_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]

    create_response = await task_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Find transformer content and summarize it."},
    )
    task_id = create_response.json()["id"]

    async with task_client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines() if line]

    events: list[str] = []
    for line in lines:
        if line.startswith("event: "):
            events.append(line.split(": ", 1)[1])

    assert events[0] == "plan"
    assert events.count("step") == 3
    assert events[-1] == "task_completed"


async def test_task_status_persists_after_failure(
    task_client: AsyncClient,
    orchestrator: AgentOrchestrator,
    session_factory,
) -> None:
    orchestrator._fake_pool.fail_on = ("web_fetch", "hacker_news_top")  # type: ignore[attr-defined]

    _, task_id = await create_session_and_task(
        task_client,
        "Find transformer content and then fetch related news.",
    )

    task_payload = await wait_for_status(task_client, task_id, "failed")
    assert "failed" in task_payload["error"]

    failed_events = await wait_for_audit_event(session_factory, "task.failed")
    assert failed_events
