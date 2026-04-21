from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
import yaml

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.models.approval import Approval
from agentforge.models.task import Task, TaskStatus
from agentforge.models.tool_call import ToolCall
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.schemas.task import PlanStep
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.replay_service import ReplayService
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 10
        self.completion_tokens = 10
        self.latency_ms = 1


class ReplayLLMProvider:
    provider_name = "mock"
    model_name = "mock-replay"

    def __init__(self) -> None:
        self.plan_text = json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-1",
                        "type": "tool_call",
                        "description": "Search the corpus.",
                        "server": "file_search",
                        "tool": "search_corpus",
                        "args": {"query": "transformer", "limit": 2},
                    },
                    {
                        "step_id": "step-2",
                        "type": "tool_call",
                        "description": "Fetch the top news item.",
                        "server": "web_fetch",
                        "tool": "hacker_news_top",
                        "args": {"count": 1},
                    },
                    {
                        "step_id": "step-3",
                        "type": "tool_call",
                        "description": "Fetch the supporting article.",
                        "server": "web_fetch",
                        "tool": "fetch_url",
                        "args": {"url": "https://example.com/post"},
                    },
                    {
                        "step_id": "step-4",
                        "type": "llm_reasoning",
                        "description": "Summarize the findings.",
                        "args": {},
                    },
                ]
            }
        )

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse("Replay completed successfully.")


class ReplayMCPPool:
    def __init__(self) -> None:
        self.fetch_url_failures_remaining = 10
        self.calls: list[tuple[str, str]] = []

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        self.calls.append((server_name, tool_name))
        if (server_name, tool_name) == ("file_search", "search_corpus"):
            return [{"filename": "transformers-overview.md"}]
        if (server_name, tool_name) == ("web_fetch", "hacker_news_top"):
            return [{"id": 1, "title": "Transformer News"}]
        if (server_name, tool_name) == ("web_fetch", "fetch_url"):
            if self.fetch_url_failures_remaining > 0:
                self.fetch_url_failures_remaining -= 1
                raise RuntimeError("fetch_url failed")
            return {"url": arguments["url"], "body": "Replay-safe article"}
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


async def wait_for_status(client: AsyncClient, task_id: str, *terminal_statuses: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        payload = (await client.get(f"/api/v1/tasks/{task_id}")).json()
        if payload["status"] in terminal_statuses:
            return payload
        if (
            "completed" in terminal_statuses
            and payload.get("final_response")
            and not payload.get("error")
        ):
            return {**payload, "status": TaskStatus.COMPLETED.value}
        if "failed" in terminal_statuses and payload.get("error") and payload.get("completed_at") is not None:
            return {**payload, "status": TaskStatus.FAILED.value}
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {terminal_statuses}")


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
async def replay_orchestrator(session_factory, guardrails_runner: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> AsyncIterator[AgentOrchestrator]:
    pool = ReplayMCPPool()
    orchestrator = AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=pool,
        llm_provider=ReplayLLMProvider(),
        event_bus=TaskEventBus(),
        guardrails_runner=guardrails_runner,
        approval_service=approval_service,
        audit_service=AuditService(),
        checkpoint_path=str(tmp_path / "replay_checkpoints.sqlite"),
    )
    orchestrator._replay_pool = pool  # type: ignore[attr-defined]
    yield orchestrator
    await orchestrator.close()


@pytest_asyncio.fixture
async def replay_app(session_factory, replay_orchestrator: AgentOrchestrator, guardrails_runner: GuardrailsRunner):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: replay_orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: replay_orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: guardrails_runner
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def replay_client(replay_app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=replay_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_replay_skips_completed_steps(
    replay_client: AsyncClient,
    replay_orchestrator: AgentOrchestrator,
    session_factory,
) -> None:
    _, task_id = await create_session_and_task(replay_client, "Search, fetch, then summarize transformer coverage.")
    task_payload = await wait_for_status(replay_client, task_id, "failed")
    assert task_payload["status"] == TaskStatus.FAILED.value

    async with session_factory() as session:
        before_counts = {
            "search_corpus": int((await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.tool_name == "search_corpus"))).scalar_one()),
            "hacker_news_top": int((await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.tool_name == "hacker_news_top"))).scalar_one()),
        }

    replay_orchestrator._replay_pool.fetch_url_failures_remaining = 0  # type: ignore[attr-defined]
    replay_response = await replay_client.post(f"/api/v1/tasks/{task_id}/replay", json={})
    assert replay_response.status_code == 202
    assert isinstance(replay_response.json()["skipped_completed_steps"], int)

    task_payload = await wait_for_status(replay_client, task_id, "completed")
    assert task_payload["status"] == TaskStatus.COMPLETED.value

    async with session_factory() as session:
        after_counts = {
            "search_corpus": int((await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.tool_name == "search_corpus"))).scalar_one()),
            "hacker_news_top": int((await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.tool_name == "hacker_news_top"))).scalar_one()),
            "fetch_url": int((await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.tool_name == "fetch_url"))).scalar_one()),
        }

    assert after_counts["search_corpus"] == before_counts["search_corpus"]
    assert after_counts["hacker_news_top"] == before_counts["hacker_news_top"]
    assert after_counts["fetch_url"] >= 2


async def test_replay_idempotency_key_stability(session_factory, approval_service: ApprovalService) -> None:
    service = ReplayService(session_factory=session_factory, approval_service=approval_service)
    step = PlanStep(
        step_id="step-2",
        type="tool_call",
        description="Fetch the top news item.",
        server="web_fetch",
        tool="hacker_news_top",
        args={"count": 1},
    )
    task_id = UUID("12345678-1234-5678-1234-567812345678")

    first = service.idempotency_key_for_step(task_id=task_id, ordinal=2, step=step)
    second = service.idempotency_key_for_step(task_id=task_id, ordinal=2, step=step)

    assert first == second


async def test_replay_409_on_completed_task(replay_client: AsyncClient, session_factory) -> None:
    _, task_id = await create_session_and_task(replay_client, "Search, fetch, then summarize transformer coverage.")
    async with session_factory() as session:
        task = await session.get(Task, UUID(task_id))
        assert task is not None
        task.status = TaskStatus.COMPLETED
        task.final_response = "Replay completed successfully."
        task.error = None
        await session.commit()

    response = await replay_client.post(f"/api/v1/tasks/{task_id}/replay", json={})
    assert response.status_code == 409


async def test_replay_idempotent_tools_only(
    replay_client: AsyncClient,
    replay_orchestrator: AgentOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    session_response = await replay_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]
    async with session_factory() as session:
        task = Task(
            session_id=UUID(session_id),
            user_prompt="Search, fetch, then summarize transformer coverage.",
            plan=json.loads(ReplayLLMProvider().plan_text)["steps"],
            status=TaskStatus.FAILED,
            error="fetch_url failed",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = str(task.id)

    original = ReplayService.is_step_idempotent
    monkeypatch.setattr(
        ReplayService,
        "is_step_idempotent",
        staticmethod(lambda step: False if step.tool == "fetch_url" else original(step)),
    )

    replay_orchestrator._replay_pool.fetch_url_failures_remaining = 0  # type: ignore[attr-defined]
    response = await replay_client.post(f"/api/v1/tasks/{task_id}/replay", json={})
    assert response.status_code == 202
    assert response.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert response.json()["approval_id"] is not None

    async with session_factory() as session:
        approval = (
            await session.execute(
                select(Approval).where(Approval.task_id == UUID(task_id)).order_by(Approval.requested_at.desc())
            )
        ).scalars().first()

    assert approval is not None
