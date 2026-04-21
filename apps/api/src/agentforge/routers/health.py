from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.config import settings
from agentforge.database import get_db
from agentforge.services.mcp_client_pool import MCPClientPool, get_mcp_client_pool

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/liveness")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
async def readiness(
    db: Annotated[AsyncSession, Depends(get_db)],
    pool: Annotated[MCPClientPool, Depends(get_mcp_client_pool)],
) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "unreachable",
                "reason": str(exc),
                "mcp_servers": {
                    "file_search": "unknown",
                    "web_fetch": "unknown",
                    "sqlite_query": "unknown",
                    "github": "unknown",
                },
            },
        )

    server_statuses = await pool.connect_all()
    mcp_servers = {name: info.status for name, info in server_statuses.items()}
    worker_status = "disabled"
    if settings.trigger_worker_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(settings.trigger_worker_url)
                worker_status = "ok" if response.status_code == 200 else "unreachable"
        except Exception:
            worker_status = "unreachable"
    if any(info.status != "ok" for info in server_statuses.values()):
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "ok",
                "mcp_servers": mcp_servers,
                "workers": {"trigger_worker": worker_status},
            },
        )
    if settings.trigger_worker_url and worker_status != "ok":
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "ok",
                "mcp_servers": mcp_servers,
                "workers": {"trigger_worker": worker_status},
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "database": "ok",
            "mcp_servers": mcp_servers,
            "workers": {"trigger_worker": worker_status},
        },
    )
