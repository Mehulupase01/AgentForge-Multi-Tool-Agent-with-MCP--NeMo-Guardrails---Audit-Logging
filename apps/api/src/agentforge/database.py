from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from agentforge.config import settings
from agentforge.models.base import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str | None = None) -> AsyncEngine:
    global _engine, _session_factory

    if _engine is None:
        _engine = create_async_engine(database_url or settings.database_url, future=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    return _engine


def get_engine() -> AsyncEngine:
    return init_engine()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    init_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


__all__ = ["Base", "dispose_engine", "get_db", "get_engine", "get_session_factory", "init_engine"]
