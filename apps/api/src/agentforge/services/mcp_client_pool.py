from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from agentforge.config import settings
from agentforge.schemas.mcp import MCPServerInfo, MCPToolDescriptor


@dataclass(slots=True)
class _ConnectedServer:
    name: str
    url: str
    label: str | None
    tools: list[MCPToolDescriptor]


class MCPClientPool:
    def __init__(
        self,
        *,
        file_search_url: str,
        web_fetch_url: str,
        sqlite_query_url: str,
        github_url: str,
    ) -> None:
        self._server_urls = {
            "file_search": file_search_url,
            "web_fetch": web_fetch_url,
            "sqlite_query": sqlite_query_url,
            "github": github_url,
        }
        self._servers: dict[str, _ConnectedServer] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._lock:
            self._servers.clear()

    async def connect_all(self, *, force_refresh: bool = False) -> dict[str, MCPServerInfo]:
        async with self._lock:
            if force_refresh:
                for server in self._servers.values():
                    await server.session_stack.aclose()
                self._servers.clear()

            statuses: dict[str, MCPServerInfo] = {}
            for name, url in self._server_urls.items():
                connected = self._servers.get(name)
                if connected is not None:
                    statuses[name] = MCPServerInfo(
                        name=name,
                        url=url,
                        status="ok",
                        tool_count=len(connected.tools),
                        server_label=connected.label,
                    )
                    continue

                try:
                    connected = await self._connect_server(name, url)
                except Exception:
                    statuses[name] = MCPServerInfo(
                        name=name,
                        url=url,
                        status="unreachable",
                        tool_count=0,
                        server_label=None,
                    )
                    continue

                self._servers[name] = connected
                statuses[name] = MCPServerInfo(
                    name=name,
                    url=url,
                    status="ok",
                    tool_count=len(connected.tools),
                    server_label=connected.label,
                )

            return statuses

    async def _connect_server(self, name: str, url: str) -> _ConnectedServer:
        async with self._session(url) as session:
            initialized = await session.initialize()
            tools_result = await session.list_tools()
        tools = [
            MCPToolDescriptor(
                server=name,
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {},
            )
            for tool in tools_result.tools
        ]
        return _ConnectedServer(
            name=name,
            url=url,
            label=initialized.serverInfo.name,
            tools=tools,
        )

    async def get_servers(self) -> list[MCPServerInfo]:
        statuses = await self.connect_all()
        return [statuses[name] for name in self._server_urls]

    async def get_tools(self) -> list[MCPToolDescriptor]:
        await self.connect_all()
        descriptors: list[MCPToolDescriptor] = []
        for name in self._server_urls:
            connected = self._servers.get(name)
            if connected is None:
                continue
            descriptors.extend(connected.tools)
        return descriptors

    async def get_tools_for_server(self, server_name: str) -> list[MCPToolDescriptor]:
        await self.connect_all()
        connected = self._servers.get(server_name)
        if connected is None:
            raise KeyError(server_name)
        return connected.tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        statuses = await self.connect_all()
        connected = self._servers.get(server_name)
        if connected is None or statuses[server_name].status != "ok":
            raise KeyError(server_name)
        async with self._session(connected.url) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
        return self._extract_tool_result(result)

    @contextlib.asynccontextmanager
    async def _session(self, url: str):
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=15.0))
        async with http_client:
            async with streamable_http_client(
                url,
                http_client=http_client,
                terminate_on_close=False,
            ) as (read, write, _):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=15),
                ) as session:
                    yield session

    def _extract_tool_result(self, result: CallToolResult) -> Any:
        if getattr(result, "structuredContent", None) is not None:
            structured = result.structuredContent
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        if not result.content:
            return None
        if len(result.content) == 1 and hasattr(result.content[0], "text"):
            text = result.content[0].text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        payload: list[Any] = []
        for item in result.content:
            payload.append(getattr(item, "text", item))
        return payload


_mcp_pool: MCPClientPool | None = None


def get_mcp_client_pool() -> MCPClientPool:
    global _mcp_pool
    if _mcp_pool is None:
        _mcp_pool = MCPClientPool(
            file_search_url=settings.mcp_file_search_url,
            web_fetch_url=settings.mcp_web_fetch_url,
            sqlite_query_url=settings.mcp_sqlite_query_url,
            github_url=settings.mcp_github_url,
        )
    return _mcp_pool
