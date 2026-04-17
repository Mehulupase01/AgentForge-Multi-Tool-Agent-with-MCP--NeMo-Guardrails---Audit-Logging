from __future__ import annotations

from collections.abc import AsyncGenerator
import json

import pytest
from httpx import Response
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

import github_mcp.server as github_server
from github_mcp.server import GITHUB_API, build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client_session() -> AsyncGenerator[ClientSession]:
    app = build_server("test-token")
    async with create_connected_server_and_client_session(app, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_list_user_repos(
    client_session: ClientSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.headers = kwargs.get("headers", {})

        async def __aenter__(self) -> StubAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params=None):
            expected_url = f"{GITHUB_API}/users/octocat/repos"
            if url == expected_url and params == {"per_page": 1, "sort": "updated"}:
                return Response(
                    200,
                    json=[{"name": "hello", "full_name": "octocat/hello", "private": False, "html_url": "https://github.com/octocat/hello"}],
                    request=github_server.httpx.Request("GET", expected_url, params=params),
                )
            raise AssertionError(f"Unexpected URL/params: {url} {params}")

    monkeypatch.setattr(github_server.httpx, "AsyncClient", StubAsyncClient)
    result = await client_session.call_tool("list_user_repos", {"username": "octocat", "limit": 1})
    payload = result.structuredContent["result"] if result.structuredContent else json.loads(result.content[0].text)
    assert payload[0]["full_name"] == "octocat/hello"


def test_github_pat_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        build_server()
