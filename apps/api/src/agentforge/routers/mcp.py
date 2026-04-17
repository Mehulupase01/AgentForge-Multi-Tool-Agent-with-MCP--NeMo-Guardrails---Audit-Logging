from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from agentforge.schemas.mcp import MCPServerInfo, MCPToolDescriptor
from agentforge.services.mcp_client_pool import MCPClientPool, get_mcp_client_pool

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/servers", response_model=list[MCPServerInfo])
async def list_mcp_servers(
    pool: Annotated[MCPClientPool, Depends(get_mcp_client_pool)],
) -> list[MCPServerInfo]:
    return await pool.get_servers()


@router.get("/servers/{server_name}/tools", response_model=list[MCPToolDescriptor])
async def list_mcp_server_tools(
    server_name: str,
    pool: Annotated[MCPClientPool, Depends(get_mcp_client_pool)],
) -> list[MCPToolDescriptor]:
    try:
        return await pool.get_tools_for_server(server_name)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "MCP server not found",
                "detail": {"server_name": server_name},
            },
        ) from exc
