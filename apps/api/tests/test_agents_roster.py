from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agentforge.database import get_db
from agentforge.main import create_app


@pytest_asyncio.fixture
async def roster_app(session_factory):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def roster_client(roster_app):
    async with AsyncClient(
        transport=ASGITransport(app=roster_app),
        base_url="http://test",
        headers={"X-API-Key": "dev-key"},
    ) as client:
        yield client


async def test_get_agents_returns_six_roles(roster_client: AsyncClient) -> None:
    response = await roster_client.get("/api/v1/agents")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert {item["role"] for item in payload} == {
        "orchestrator",
        "analyst",
        "researcher",
        "engineer",
        "secretary",
        "security_officer",
    }


async def test_capabilities_enforce_tool_scope(roster_client: AsyncClient) -> None:
    response = await roster_client.get("/api/v1/agents/analyst/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "analyst"
    assert "sqlite_query.list_employees" in payload["tools"]
    assert all(not tool.startswith("github.") for tool in payload["tools"])
