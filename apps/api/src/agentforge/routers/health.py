from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db

router = APIRouter(prefix="/api/v1/health", tags=["health"])

MCP_STUB = {
    "file_search": "not_configured",
    "web_fetch": "not_configured",
    "sqlite_query": "not_configured",
    "github": "not_configured",
}


@router.get("/liveness")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readiness")
async def readiness(db: Annotated[AsyncSession, Depends(get_db)]) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "database": "unreachable",
                "reason": str(exc),
                "mcp_servers": MCP_STUB,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "database": "ok",
            "mcp_servers": MCP_STUB,
        },
    )
