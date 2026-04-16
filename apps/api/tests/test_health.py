from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from agentforge.database import get_db
from agentforge.main import create_app


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


async def test_app_factory_loads() -> None:
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "AgentForge API"
