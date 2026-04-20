from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import yaml

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.models.approval import Approval
from agentforge.models.audit_event import AuditEvent
from agentforge.models.task import TaskStatus
from agentforge.models.task_step import StepType, TaskStep
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus
from agentforge.models.base import Base
import agentforge.models  # noqa: F401


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 10
        self.completion_tokens = 15
        self.latency_ms = 1


class HealingLLMProvider:
    provider_name = "mock"
    model_name = "mock-healing"

    def __init__(self) -> None:
        self.plan_text = json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "type": "tool_call",
                        "description": "Fetch related news.",
                        "server": "web_fetch",
                        "tool": "hacker_news_top",
                        "args": {"count": 1},
                    }
                ]
            }
        )

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(f"reflection::{user_prompt}")


class FlakyWebFetchPool:
    def __init__(self, *, fail_count: int) -> None:
        self.fail_count = fail_count
        self.calls = 0

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise httpx.TimeoutException("web_fetch timed out")
        return [{"id": 101, "title": "Recovered article", "score": 88}]


def write_allowlist(path: Path, *, web_fetch_allowed: bool = True) -> Path:
    payload = {
        "allowlist": {
            "file_search": ["search_corpus", "read_document"],
            "web_fetch": ["fetch_url", "hacker_news_top", "weather_for"] if web_fetch_allowed else ["fetch_url", "weather_for"],
            "sqlite_query": ["list_employees", "list_projects", "run_select"],
            "github": ["list_user_repos", "search_issues", "get_repo"],
        }
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


@pytest_asyncio.fixture(loop_scope="module")
async def session_factory(tmp_path: Path):
    database_path = (tmp_path / "self_healing_test.sqlite").resolve()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory

    await engine.dispose()


async def wait_for_status(client: AsyncClient, task_id: str, *terminal_statuses: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/tasks/{task_id}")
        payload = response.json()
        if payload["status"] in terminal_statuses:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {terminal_statuses}")


async def create_session_and_task(client: AsyncClient, prompt: str) -> tuple[str, str]:
    session_response = await client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]
    task_response = await client.post(f"/api/v1/sessions/{session_id}/tasks", json={"user_prompt": prompt})
    return session_id, task_response.json()["id"]


async def wait_for_approval(session_factory, task_id: str) -> Approval:
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            approval = (
                await session.execute(
                    select(Approval).where(Approval.task_id == UUID(task_id)).order_by(Approval.requested_at.desc())
                )
            ).scalars().first()
        if approval is not None:
            return approval
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for approval on task {task_id}")


def build_orchestrator(session_factory, guardrails_runner: GuardrailsRunner, tmp_path: Path, fail_count: int) -> AgentOrchestrator:
    checkpoint_name = f"self_healing_{tmp_path.name}_{fail_count}.sqlite"
    return AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=FlakyWebFetchPool(fail_count=fail_count),
        llm_provider=HealingLLMProvider(),
        event_bus=TaskEventBus(),
        guardrails_runner=guardrails_runner,
        approval_service=ApprovalService(),
        audit_service=AuditService(),
        checkpoint_path=str((Path.cwd() / checkpoint_name).resolve()),
    )


@pytest_asyncio.fixture(loop_scope="module")
async def guardrails_runner(tmp_path: Path) -> GuardrailsRunner:
    return GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "tool_allowlist.yml")))


async def build_client(session_factory, orchestrator: AgentOrchestrator, guardrails_runner: GuardrailsRunner):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner
    return app


async def test_transient_error_retries_and_succeeds(session_factory, guardrails_runner: GuardrailsRunner, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(session_factory, guardrails_runner, tmp_path, fail_count=1)
    app = await build_client(session_factory, orchestrator, guardrails_runner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "dev-key"}) as client:
        _, task_id = await create_session_and_task(client, "Fetch related news and summarize it.")
        payload = await wait_for_status(client, task_id, "completed")
        assert payload["status"] == TaskStatus.COMPLETED.value

    await asyncio.sleep(0.1)
    async with session_factory() as session:
        steps = list((await session.execute(select(TaskStep).where(TaskStep.task_id == UUID(task_id)).order_by(TaskStep.ordinal.asc()))).scalars())

    assert [step.step_type for step in steps] == [StepType.TOOL_CALL, StepType.REFLECTION, StepType.RETRY]
    assert [step.attempt for step in steps] == [1, 1, 2]

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_three_retries_then_escalate_to_hitl(session_factory, guardrails_runner: GuardrailsRunner, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(session_factory, guardrails_runner, tmp_path, fail_count=3)
    app = await build_client(session_factory, orchestrator, guardrails_runner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "dev-key"}) as client:
        _, task_id = await create_session_and_task(client, "Fetch related news and summarize it.")
        payload = await wait_for_status(client, task_id, "awaiting_approval")
        assert payload["status"] == TaskStatus.AWAITING_APPROVAL.value

    approval = await wait_for_approval(session_factory, task_id)
    assert approval.risk_level.value == "medium"
    assert "timed out" in approval.risk_reason.lower()

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_guardrail_block_does_not_retry(session_factory, tmp_path: Path) -> None:
    runner = GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "disallow_web_fetch.yml", web_fetch_allowed=False)))
    orchestrator = build_orchestrator(session_factory, runner, tmp_path, fail_count=0)
    app = await build_client(session_factory, orchestrator, runner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "dev-key"}) as client:
        _, task_id = await create_session_and_task(client, "Fetch related news and summarize it.")
        await wait_for_status(client, task_id, "completed")

    async with session_factory() as session:
        retry_steps = list((await session.execute(select(TaskStep).where(TaskStep.task_id == UUID(task_id), TaskStep.step_type == StepType.RETRY))).scalars())

    assert retry_steps == []

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_reflection_uses_error_as_context(session_factory, guardrails_runner: GuardrailsRunner, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(session_factory, guardrails_runner, tmp_path, fail_count=1)
    app = await build_client(session_factory, orchestrator, guardrails_runner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "dev-key"}) as client:
        _, task_id = await create_session_and_task(client, "Fetch related news and summarize it.")
        await wait_for_status(client, task_id, "completed")

    await asyncio.sleep(0.1)
    async with session_factory() as session:
        reflection_step = (
            await session.execute(
                select(TaskStep).where(TaskStep.task_id == UUID(task_id), TaskStep.step_type == StepType.REFLECTION)
            )
        ).scalars().first()

    assert reflection_step is not None
    assert "web_fetch timed out" in json.dumps(reflection_step.input_json)
    assert '"count": 1' in json.dumps(reflection_step.input_json)

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_audit_emits_agent_retry(session_factory, guardrails_runner: GuardrailsRunner, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(session_factory, guardrails_runner, tmp_path, fail_count=1)
    app = await build_client(session_factory, orchestrator, guardrails_runner)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "dev-key"}) as client:
        _, task_id = await create_session_and_task(client, "Fetch related news and summarize it.")
        await wait_for_status(client, task_id, "completed")

    async with session_factory() as session:
        events = list((await session.execute(select(AuditEvent).where(AuditEvent.event_type == "agent.retry"))).scalars())

    assert events
    assert any(event.task_id == UUID(task_id) for event in events)

    await orchestrator.close()
    app.dependency_overrides.clear()
