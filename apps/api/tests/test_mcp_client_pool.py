from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentforge.database import get_db
from agentforge.main import create_app
from agentforge.services.mcp_client_pool import MCPClientPool, get_mcp_client_pool

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = REPO_ROOT / "fixtures" / "corpus"
SYNTHETIC_DB_PATH = REPO_ROOT / "fixtures" / "synthetic.sqlite"

SIDECARS = {
    "file_search": {
        "module": "file_search.server",
        "port": 8101,
        "src": REPO_ROOT / "apps" / "mcp_servers" / "file_search" / "src",
    },
    "web_fetch": {
        "module": "web_fetch.server",
        "port": 8102,
        "src": REPO_ROOT / "apps" / "mcp_servers" / "web_fetch" / "src",
    },
    "sqlite_query": {
        "module": "sqlite_query.server",
        "port": 8103,
        "src": REPO_ROOT / "apps" / "mcp_servers" / "sqlite_query" / "src",
    },
    "github": {
        "module": "github_mcp.server",
        "port": 8104,
        "src": REPO_ROOT / "apps" / "mcp_servers" / "github" / "src",
    },
}


def _wait_for_port(port: int, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for port {port}")


@pytest.fixture(scope="session")
def sidecar_processes() -> Iterator[dict[str, subprocess.Popen[str]]]:
    env = os.environ.copy()
    env["CORPUS_PATH"] = str(CORPUS_PATH)
    env["SYNTHETIC_DB_PATH"] = str(SYNTHETIC_DB_PATH)
    env["GITHUB_TOKEN"] = env.get("GITHUB_TOKEN", "test-token")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(config["src"]) for config in SIDECARS.values()] + [env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    processes: dict[str, subprocess.Popen[str]] = {}
    try:
        for name, config in SIDECARS.items():
            process = subprocess.Popen(
                [sys.executable, "-m", config["module"]],
                cwd=str(REPO_ROOT),
                env={**env, "PORT": str(config["port"])},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes[name] = process
            _wait_for_port(config["port"])
        yield processes
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.fixture
async def pool(sidecar_processes) -> Iterator[MCPClientPool]:
    client_pool = MCPClientPool(
        file_search_url="http://127.0.0.1:8101/mcp",
        web_fetch_url="http://127.0.0.1:8102/mcp",
        sqlite_query_url="http://127.0.0.1:8103/mcp",
        github_url="http://127.0.0.1:8104/mcp",
    )
    yield client_pool
    await client_pool.close()


async def test_pool_discovers_all_servers(pool: MCPClientPool) -> None:
    statuses = await pool.connect_all()
    assert set(statuses) == {"file_search", "web_fetch", "sqlite_query", "github"}
    assert all(info.status == "ok" for info in statuses.values())


async def test_pool_lists_expected_tools(pool: MCPClientPool) -> None:
    tools = await pool.get_tools()
    tool_names = {f"{tool.server}.{tool.name}" for tool in tools}
    assert "file_search.search_corpus" in tool_names
    assert "web_fetch.fetch_url" in tool_names
    assert "sqlite_query.list_employees" in tool_names
    assert "github.list_user_repos" in tool_names


async def test_pool_call_tool_returns_fixture_results(pool: MCPClientPool) -> None:
    result = await pool.call_tool("file_search", "search_corpus", {"query": "transformer"})
    assert result
    assert result[0]["filename"].endswith(".md")


async def test_readiness_includes_mcp_status(pool: MCPClientPool) -> None:
    app = create_app()

    app.dependency_overrides[get_mcp_client_pool] = lambda: pool

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/readiness")

    assert response.status_code == 200
    assert response.json()["mcp_servers"]["file_search"] == "ok"


async def test_readiness_reports_unreachable_server(session_factory, sidecar_processes) -> None:
    broken_pool = MCPClientPool(
        file_search_url="http://127.0.0.1:8101/mcp",
        web_fetch_url="http://127.0.0.1:8102/mcp",
        sqlite_query_url="http://127.0.0.1:8103/mcp",
        github_url="http://127.0.0.1:8999/mcp",
    )
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_mcp_client_pool] = lambda: broken_pool

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/readiness")

    assert response.status_code == 503
    assert response.json()["mcp_servers"]["github"] == "unreachable"
    await broken_pool.close()
