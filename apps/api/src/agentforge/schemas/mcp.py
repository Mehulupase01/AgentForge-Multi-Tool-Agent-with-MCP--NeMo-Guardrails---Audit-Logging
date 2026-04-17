from __future__ import annotations

from pydantic import BaseModel


class MCPServerInfo(BaseModel):
    name: str
    url: str
    status: str
    tool_count: int
    server_label: str | None = None


class MCPToolDescriptor(BaseModel):
    server: str
    name: str
    description: str
    input_schema: dict
