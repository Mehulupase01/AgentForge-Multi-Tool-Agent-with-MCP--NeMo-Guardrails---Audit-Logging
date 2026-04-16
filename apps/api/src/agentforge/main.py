from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentforge import __version__
from agentforge.auth import require_api_key
from agentforge.config import settings
from agentforge.database import dispose_engine, init_engine
from agentforge.logging_setup import configure_logging
from agentforge.routers.audit import router as audit_router
from agentforge.routers.corpus import router as corpus_router
from agentforge.routers.health import router as health_router
from agentforge.routers.sessions import router as sessions_router

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

    def error_response(
        status_code: int,
        code: str,
        message: str,
        detail: dict | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "detail": detail or {},
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
            return error_response(
                exc.status_code,
                exc.detail["code"],
                exc.detail["message"],
                exc.detail.get("detail", {}),
            )

        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            409: "CONFLICT",
        }
        return error_response(
            exc.status_code,
            code_map.get(exc.status_code, "BAD_REQUEST"),
            str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            {"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("request.failed", path=str(request.url.path), error=str(exc))
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Internal server error",
            {"path": str(request.url.path)},
        )

    app.include_router(health_router)
    app.include_router(sessions_router, dependencies=[Depends(require_api_key)])
    app.include_router(audit_router, dependencies=[Depends(require_api_key)])
    app.include_router(corpus_router, dependencies=[Depends(require_api_key)])

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
