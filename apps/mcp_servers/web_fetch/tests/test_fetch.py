from __future__ import annotations

from collections.abc import AsyncGenerator
import json

import pytest
from httpx import Response
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

import web_fetch.server as web_fetch_server
from web_fetch.server import build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client_session() -> AsyncGenerator[ClientSession]:
    app = build_server()
    async with create_connected_server_and_client_session(app, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_hacker_news_top_returns_items(
    client_session: ClientSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self) -> StubAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params=None):
            if url == "https://hacker-news.firebaseio.com/v0/topstories.json":
                return Response(200, json=[101], request=web_fetch_server.httpx.Request("GET", url))
            if url == "https://hacker-news.firebaseio.com/v0/item/101.json":
                return Response(
                    200,
                    json={"id": 101, "title": "Test Story", "url": "https://example.com", "score": 42},
                    request=web_fetch_server.httpx.Request("GET", url),
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(web_fetch_server.httpx, "AsyncClient", StubAsyncClient)
    result = await client_session.call_tool("hacker_news_top", {"count": 1})
    payload = result.structuredContent["result"] if result.structuredContent else json.loads(result.content[0].text)
    assert payload[0]["title"] == "Test Story"


@pytest.mark.anyio
async def test_web_fetch_allowlist(client_session: ClientSession) -> None:
    result = await client_session.call_tool("fetch_url", {"url": "https://malicious.example.com"})
    assert result.isError is True
