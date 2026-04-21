from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from agentforge.config import settings
from agentforge.database import get_db
from agentforge.main import create_app
from agentforge.models.audit_event import AuditEvent
from agentforge.models.task import Task
from agentforge.models.trigger import Trigger, TriggerEvent, TriggerEventStatus, TriggerSource, TriggerStatus
from agentforge.routers.tasks import orchestrator_dependency


FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "triggers" / "github_issue_opened.json"


class StubOrchestrator:
    def __init__(self) -> None:
        self.started_task_ids: list[str] = []

    def start_task(self, task_id, **kwargs) -> None:
        self.started_task_ids.append(str(task_id))


def sign_github(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def sign_generic(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def trigger_client(session_factory):
    app = create_app()
    orchestrator = StubOrchestrator()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[orchestrator_dependency] = lambda: orchestrator

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client, orchestrator

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_github_trigger(trigger_client) -> None:
    client, _ = trigger_client
    response = await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "issues-opened"
    assert "secret" not in payload


@pytest.mark.asyncio
async def test_github_webhook_hmac_valid(trigger_client, session_factory) -> None:
    client, orchestrator = trigger_client
    create = await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )
    assert create.status_code == 201

    body = FIXTURE.read_bytes()
    response = await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": sign_github("topsecret", body),
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["task_id"] is not None
    assert payload["task_id"] in orchestrator.started_task_ids

    async with session_factory() as session:
        event = await session.get(TriggerEvent, UUID(payload["trigger_event_id"]))
        assert event is not None
        assert event.signature_valid is True
        assert event.status == TriggerEventStatus.ACCEPTED


@pytest.mark.asyncio
async def test_github_webhook_hmac_invalid(trigger_client, session_factory) -> None:
    client, _ = trigger_client
    await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )

    body = FIXTURE.read_bytes()
    response = await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": "sha256=bad",
        },
    )
    assert response.status_code == 401

    async with session_factory() as session:
        event = (await session.execute(select(TriggerEvent).order_by(TriggerEvent.received_at.desc()))).scalars().first()
        assert event is not None
        assert event.signature_valid is False
        assert event.status == TriggerEventStatus.REJECTED


@pytest.mark.asyncio
async def test_disabled_trigger_rejects(trigger_client, session_factory) -> None:
    client, _ = trigger_client
    create = await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )
    trigger_id = create.json()["id"]
    patch = await client.patch(f"/api/v1/triggers/{trigger_id}", json={"status": "disabled"})
    assert patch.status_code == 200

    body = FIXTURE.read_bytes()
    response = await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": sign_github("topsecret", body),
        },
    )
    assert response.status_code == 409

    async with session_factory() as session:
        event = (await session.execute(select(TriggerEvent).order_by(TriggerEvent.received_at.desc()))).scalars().first()
        assert event is not None
        assert event.status == TriggerEventStatus.REJECTED


@pytest.mark.asyncio
async def test_schedule_trigger_fires_task(trigger_client, session_factory) -> None:
    client, orchestrator = trigger_client
    create = await client.post(
        "/api/v1/triggers",
        json={
            "name": "scheduled-digest",
            "source": "schedule",
            "config": {"cron": "*/5 * * * *"},
            "prompt_template": "Run scheduled digest",
        },
    )
    trigger_id = create.json()["id"]

    response = await client.post("/api/v1/triggers/internal/fire", json={"trigger_id": trigger_id})
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["task_id"] in orchestrator.started_task_ids

    async with session_factory() as session:
        task = await session.get(Task, UUID(payload["task_id"]))
        assert task is not None
        assert str(task.trigger_event_id) == payload["trigger_event_id"]


@pytest.mark.asyncio
async def test_webhook_creates_task_with_template(trigger_client, session_factory) -> None:
    client, _ = trigger_client
    await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )

    body = FIXTURE.read_bytes()
    response = await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": sign_github("topsecret", body),
        },
    )
    task_id = response.json()["task_id"]
    async with session_factory() as session:
        task = await session.get(Task, UUID(task_id))
        assert task is not None
        assert task.user_prompt == "Fix Null ptr"


@pytest.mark.asyncio
async def test_audit_emits_trigger_events(trigger_client, session_factory) -> None:
    client, _ = trigger_client
    await client.post(
        "/api/v1/triggers",
        json={
            "name": "issues-opened",
            "source": "github_webhook",
            "config": {"event": "issues.opened"},
            "prompt_template": "Fix {{ issue.title }}",
            "secret": "topsecret",
        },
    )

    body = FIXTURE.read_bytes()
    await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": sign_github("topsecret", body),
        },
    )
    await client.post(
        "/api/v1/triggers/webhook/github",
        content=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-hub-signature-256": "sha256=bad",
        },
    )

    async with session_factory() as session:
        event_types = [event.event_type for event in (await session.execute(select(AuditEvent).order_by(AuditEvent.sequence.asc()))).scalars()]
        assert "trigger.received" in event_types
        assert "trigger.fired" in event_types
        assert "trigger.rejected" in event_types


@pytest.mark.asyncio
async def test_generic_webhook_uses_env_secret_fallback(trigger_client, session_factory) -> None:
    client, orchestrator = trigger_client
    previous_secret = settings.generic_webhook_secret
    settings.generic_webhook_secret = "genericsecret"
    try:
        create = await client.post(
            "/api/v1/triggers",
            json={
                "name": "generic-alert",
                "source": "generic_webhook",
                "config": {"event": "generic.alert"},
                "prompt_template": "Handle {{ title }}",
            },
        )
        assert create.status_code == 201

        body = json.dumps({"title": "Security alert"}).encode("utf-8")
        response = await client.post(
            "/api/v1/triggers/webhook/generic",
            content=body,
            headers={
                "content-type": "application/json",
                "x-signature-256": sign_generic("genericsecret", body),
            },
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["task_id"] in orchestrator.started_task_ids

        async with session_factory() as session:
            event = await session.get(TriggerEvent, UUID(payload["trigger_event_id"]))
            assert event is not None
            assert event.signature_valid is True
    finally:
        settings.generic_webhook_secret = previous_secret
