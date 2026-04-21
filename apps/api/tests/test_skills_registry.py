from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
import yaml

from agentforge.database import get_db
from agentforge.guardrails.runner import GuardrailsRunner, get_guardrails_runner
from agentforge.guardrails.tool_allowlist import ToolAllowlist
from agentforge.main import create_app
from agentforge.models.agent_run import AgentRun, AgentRole
from agentforge.models.approval import Approval, RiskLevel
from agentforge.models.audit_event import AuditEvent
from agentforge.models.skill import SkillInvocation
from agentforge.models.task_step import TaskStep
from agentforge.routers.tasks import orchestrator_dependency
from agentforge.services.agent_orchestrator import AgentOrchestrator
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.skills_registry import SkillsRegistry
import agentforge.services.skills_registry as skills_registry_service
from agentforge.services.task_event_bus import TaskEventBus, get_task_event_bus

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_SKILLS_DIR = REPO_ROOT / "apps" / "api" / "src" / "agentforge" / "skills"


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 10
        self.completion_tokens = 15
        self.latency_ms = 1


class RoutedSkillsProvider:
    provider_name = "mock"
    model_name = "mock-skills"

    def __init__(self, handoffs: list[dict]) -> None:
        self.plan_text = json.dumps({"handoffs": handoffs})

    async def generate_plan(self, user_prompt: str) -> MockLLMResponse:
        raise AssertionError("Supervisor-only skills tests should not call generate_plan.")

    async def generate_supervisor_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(self.plan_text)

    async def compose_multi_agent_summary(self, user_prompt: str, specialist_results: list[dict]) -> str:
        return " ".join(item["summary"] for item in specialist_results)

    async def reason_step(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse("unused")


class SkillsMCPPool:
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        if (server_name, tool_name) == ("sqlite_query", "list_employees"):
            return [
                {
                    "employee_id": index,
                    "name": f"Engineer {index}",
                    "department": arguments.get("department") or "Engineering",
                    "salary_band": "P3",
                }
                for index in range(1, 101)
            ]
        if (server_name, tool_name) == ("sqlite_query", "run_select"):
            return [
                {
                    "employee_id": 1,
                    "project_name": "Atlas",
                    "salary_band": "P4",
                }
            ]
        if (server_name, tool_name) == ("github", "get_repo"):
            owner = arguments.get("owner", "openai")
            name = arguments.get("name", "agentforge")
            return {"full_name": f"{owner}/{name}", "open_issues_count": 7}
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
        response = await client.get(f"/api/v1/tasks/{task_id}")
        payload = response.json()
        if payload["status"] in terminal_statuses:
            return payload
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id} to reach {terminal_statuses}")


async def wait_for_task_approval(session_factory, task_id: str) -> Approval:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            approval = (
                await session.execute(
                    select(Approval)
                    .where(Approval.task_id == UUID(task_id))
                    .order_by(Approval.requested_at.desc())
                )
            ).scalars().first()
        if approval is not None:
            return approval
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for approval rows for task {task_id}")


async def wait_for_task_step(session_factory, task_id: str) -> TaskStep:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as session:
            step = (
                await session.execute(
                    select(TaskStep)
                    .where(TaskStep.task_id == UUID(task_id))
                    .order_by(TaskStep.ordinal.desc())
                )
            ).scalars().first()
        if step is not None:
            return step
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task steps for task {task_id}")


def copy_skill_bundle(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for path in SOURCE_SKILLS_DIR.glob("*.yml"):
        shutil.copy2(path, destination / path.name)
    return destination


def build_orchestrator(
    session_factory,
    registry: SkillsRegistry,
    provider: RoutedSkillsProvider,
    guardrails_runner: GuardrailsRunner,
    approval_service: ApprovalService,
    tmp_path: Path,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        session_factory=session_factory,
        mcp_pool=SkillsMCPPool(),
        llm_provider=provider,
        event_bus=TaskEventBus(),
        guardrails_runner=guardrails_runner,
        approval_service=approval_service,
        audit_service=AuditService(),
        checkpoint_path=str(tmp_path / "skills_checkpoints.sqlite"),
        skills_registry=registry,
    )


@pytest_asyncio.fixture
async def skills_guardrails(tmp_path: Path) -> GuardrailsRunner:
    return GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "tool_allowlist.yml")))


@pytest_asyncio.fixture
async def approval_service() -> ApprovalService:
    return ApprovalService()


@pytest_asyncio.fixture
async def skills_registry(session_factory, tmp_path: Path):
    registry = SkillsRegistry(
        session_factory=session_factory,
        skills_path=copy_skill_bundle(tmp_path / "skills"),
    )
    previous = skills_registry_service._skills_registry
    skills_registry_service._skills_registry = registry
    await registry.load_all()
    yield registry
    skills_registry_service._skills_registry = previous


@pytest_asyncio.fixture
async def skills_app(session_factory, skills_registry: SkillsRegistry, skills_guardrails: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path):
    provider = RoutedSkillsProvider(
        [
            {
                "to": "analyst",
                "reason": "List engineering employees from the workforce database.",
                "payload": {"department": "Engineering", "limit": 100, "description": "List engineering employees."},
            }
        ]
    )
    orchestrator = build_orchestrator(session_factory, skills_registry, provider, skills_guardrails, approval_service, tmp_path)
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: skills_guardrails
    app.dependency_overrides[skills_registry_service.get_skills_registry] = lambda: skills_registry
    yield app, orchestrator
    await orchestrator.close()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def skills_client(skills_app):
    app, _ = skills_app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_skills_load_from_yaml(skills_client: AsyncClient, skills_registry: SkillsRegistry) -> None:
    response = await skills_client.get("/api/v1/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["total"] == 4
    assert len(skills_registry.list_active_skills()) == 4
    assert all(len(skill.content_hash) == 64 for skill in skills_registry.list_active_skills())


async def test_reload_detects_change(skills_client: AsyncClient, skills_registry: SkillsRegistry) -> None:
    skill_file = skills_registry.resolve_path() / "repo_health.yml"
    original = yaml.safe_load(skill_file.read_text(encoding="utf-8"))
    original["description"] = "Inspect repository health and issue backlog signals."
    skill_file.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    response = await skills_client.post("/api/v1/skills/reload")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"loaded": 4, "updated": 1, "removed": 0}


async def test_policy_max_results_truncates(skills_client: AsyncClient, session_factory) -> None:
    session_response = await skills_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]

    create_response = await skills_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Compare employees and github noise for the operator."},
    )
    task_id = create_response.json()["id"]
    step = await wait_for_task_step(session_factory, task_id)

    assert isinstance(step.output_json, dict)
    assert step.output_json["metadata"]["truncated_to"] == 50
    assert len(step.output_json["result"]) == 50


async def test_policy_forbid_fields_redacts(skills_client: AsyncClient, session_factory) -> None:
    session_response = await skills_client.post("/api/v1/sessions", json={})
    session_id = session_response.json()["id"]

    create_response = await skills_client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"user_prompt": "Compare employees and github noise for the operator."},
    )
    task_id = create_response.json()["id"]

    step = await wait_for_task_step(session_factory, task_id)
    async with session_factory() as session:
        invocation = (
            await session.execute(
                select(SkillInvocation).where(SkillInvocation.task_step_id == step.id)
            )
        ).scalars().first()
        violations = list(
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.task_id == UUID(task_id),
                        AuditEvent.event_type == "skill.policy_violation",
                    )
                )
            ).scalars()
        )

    assert invocation is not None
    assert invocation.policy_checks_json["forbid_fields"]["detail"]["applied"] is True
    assert all("salary_band" not in row for row in step.output_json["result"])
    assert violations == []


async def test_policy_require_approval_if_join_contains(session_factory, skills_registry: SkillsRegistry, skills_guardrails: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> None:
    provider = RoutedSkillsProvider(
        [
            {
                "to": "analyst",
                "reason": "Investigate workforce salary joins.",
                "payload": {
                    "sql": "SELECT e.name, c.salary_band FROM employees e JOIN compensation c ON e.salary_band = c.salary_band",
                    "description": "Investigate workforce salary joins.",
                },
            }
        ]
    )
    orchestrator = build_orchestrator(session_factory, skills_registry, provider, skills_guardrails, approval_service, tmp_path)
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: skills_guardrails
    app.dependency_overrides[skills_registry_service.get_skills_registry] = lambda: skills_registry

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        session_response = await client.post("/api/v1/sessions", json={})
        session_id = session_response.json()["id"]
        create_response = await client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": "Review employees compensation and github noise for context."},
        )
        task_id = create_response.json()["id"]
        approval = await wait_for_task_approval(session_factory, task_id)
        payload = (await client.get(f"/api/v1/tasks/{task_id}")).json()
        assert payload["status"] == "awaiting_approval"

    assert approval is not None
    assert approval.risk_level == RiskLevel.MEDIUM

    await orchestrator.close()
    app.dependency_overrides.clear()


async def test_policy_topic_scope_blocks_out_of_scope(session_factory, skills_registry: SkillsRegistry, skills_guardrails: GuardrailsRunner, approval_service: ApprovalService, tmp_path: Path) -> None:
    provider = RoutedSkillsProvider(
        [
            {
                "to": "analyst",
                "reason": "Review repository health details.",
                "payload": {
                    "repo": "openai/agentforge",
                    "description": "Review repository health details.",
                },
            }
        ]
    )
    orchestrator = build_orchestrator(session_factory, skills_registry, provider, skills_guardrails, approval_service, tmp_path)
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator
    app.dependency_overrides[get_task_event_bus] = lambda: orchestrator._event_bus  # type: ignore[attr-defined]
    app.dependency_overrides[get_guardrails_runner] = lambda: skills_guardrails
    app.dependency_overrides[skills_registry_service.get_skills_registry] = lambda: skills_registry

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        session_response = await client.post("/api/v1/sessions", json={})
        session_id = session_response.json()["id"]
        create_response = await client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": "Assess github repo health and web research for the operator."},
        )
        task_id = create_response.json()["id"]
        payload = await wait_for_status(client, task_id, "completed")
        assert "Engineer inspected repository data" in payload["final_response"]

    async with session_factory() as session:
        violations = list(
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.task_id == UUID(task_id),
                        AuditEvent.event_type == "skill.policy_violation",
                    )
                )
            ).scalars()
        )
        runs = list((await session.execute(select(AgentRun).where(AgentRun.task_id == UUID(task_id)))).scalars())

    assert violations
    assert {run.role for run in runs} >= {AgentRole.ANALYST, AgentRole.ENGINEER}

    await orchestrator.close()
    app.dependency_overrides.clear()
