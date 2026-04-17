from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from file_search.server import build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client_session(tmp_path: Path) -> AsyncGenerator[ClientSession]:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "alpha.md").write_text(
        "---\n"
        "title: Neural Network Basics\n"
        "---\n\n"
        "# Neural Network Basics\n\n"
        "Neural network systems learn dense representations from data.\n",
        encoding="utf-8",
    )
    app = build_server(corpus_dir)
    async with create_connected_server_and_client_session(app, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_file_search_returns_results(client_session: ClientSession) -> None:
    result = await client_session.call_tool("search_corpus", {"query": "neural network"})
    assert result.structuredContent
    assert result.structuredContent["result"][0]["filename"] == "alpha.md"


@pytest.mark.anyio
async def test_file_search_handles_simple_pluralization(client_session: ClientSession) -> None:
    result = await client_session.call_tool("search_corpus", {"query": "neural networks"})
    assert result.structuredContent
    assert result.structuredContent["result"][0]["filename"] == "alpha.md"


@pytest.mark.anyio
async def test_read_document_returns_content(client_session: ClientSession) -> None:
    result = await client_session.call_tool("read_document", {"filename": "alpha.md"})
    payload = json.loads(result.content[0].text)
    assert payload["title"] == "Neural Network Basics"
    assert "Neural network systems" in payload["content"]
