from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from sqlite_query.server import build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def synthetic_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "synthetic.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE employees (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              department TEXT NOT NULL,
              role TEXT NOT NULL,
              hire_date TEXT NOT NULL,
              salary_band INTEGER NOT NULL
            );
            CREATE TABLE projects (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              owner_employee_id TEXT NOT NULL,
              status TEXT NOT NULL,
              budget_eur INTEGER NOT NULL,
              start_date TEXT NOT NULL,
              end_date TEXT
            );
            INSERT INTO employees VALUES ('e1', 'Alice Doe', 'alice@example.com', 'engineering', 'ML Engineer', '2024-01-01', 5);
            INSERT INTO projects VALUES ('p1', 'Atlas', 'e1', 'active', 100000, '2024-01-01', NULL);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return db_path


@pytest.fixture
async def client_session(synthetic_db: Path) -> AsyncGenerator[ClientSession]:
    app = build_server(synthetic_db)
    async with create_connected_server_and_client_session(app, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_list_employees(client_session: ClientSession) -> None:
    result = await client_session.call_tool("list_employees", {"department": "engineering"})
    assert result.structuredContent["result"][0]["name"] == "Alice Doe"


@pytest.mark.anyio
async def test_sqlite_query_rejects_non_select(client_session: ClientSession) -> None:
    result = await client_session.call_tool("run_select", {"sql": "DELETE FROM employees"})
    assert result.isError is True
