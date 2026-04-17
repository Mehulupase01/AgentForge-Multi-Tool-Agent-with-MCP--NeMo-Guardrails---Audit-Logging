from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from agentforge.database import get_db
from agentforge.main import create_app
from agentforge.services.mcp_client_pool import get_mcp_client_pool


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_db_up(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


async def test_readiness_db_down() -> None:
    app = create_app()

    class BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    async def broken_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/readiness")

    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


async def test_readiness_with_pool_override() -> None:
    app = create_app()

    class HealthySession:
        async def execute(self, *_args, **_kwargs):
            return None

    class HealthyPool:
        async def connect_all(self):
            return {
                "file_search": type("Info", (), {"status": "ok"})(),
                "web_fetch": type("Info", (), {"status": "ok"})(),
                "sqlite_query": type("Info", (), {"status": "ok"})(),
                "github": type("Info", (), {"status": "ok"})(),
            }

    async def healthy_get_db():
        yield HealthySession()

    app.dependency_overrides[get_db] = healthy_get_db
    app.dependency_overrides[get_mcp_client_pool] = lambda: HealthyPool()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/readiness")

    assert response.status_code == 200
    assert response.json()["mcp_servers"]["github"] == "ok"


async def test_app_factory_loads() -> None:
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AgentForge API"
