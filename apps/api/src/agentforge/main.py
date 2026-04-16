from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentforge import __version__
from agentforge.config import settings
from agentforge.database import dispose_engine, init_engine
from agentforge.logging_setup import configure_logging
from agentforge.routers.health import router as health_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_engine()
    logger.info("application.startup", database_url=settings.database_url)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("application.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentForge API",
        version=__version__,
        description=(
            "Enterprise-safe agentic AI platform with MCP tool calling, guardrails, "
            "human approvals, and tamper-evident audit logging."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                    "path": str(request.url.path),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("request.failed", path=str(request.url.path), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Internal server error",
                    "path": str(request.url.path),
                }
            },
        )

    app.include_router(health_router)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "agentforge.main:app",
        host="0.0.0.0",
        port=settings.api_port,
        app_dir="src",
        reload=settings.debug,
    )
