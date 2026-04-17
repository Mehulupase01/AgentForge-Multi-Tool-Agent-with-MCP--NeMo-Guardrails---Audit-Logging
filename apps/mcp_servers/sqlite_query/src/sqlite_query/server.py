from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import sqlparse
from mcp.server.fastmcp import FastMCP

DEFAULT_DB_PATH = Path(os.getenv("SYNTHETIC_DB_PATH", "/data/synthetic.sqlite"))


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _validate_select(sql: str) -> None:
    statements = [stmt for stmt in sqlparse.parse(sql) if stmt.tokens]
    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed")
    statement = statements[0]
    if statement.get_type() != "SELECT":
        raise ValueError("Only SELECT statements are allowed")


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def build_server(db_path: Path | None = None) -> FastMCP:
    query_db_path = db_path or DEFAULT_DB_PATH
    mcp = FastMCP(
        "sqlite_query",
        json_response=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8103")),
        streamable_http_path="/mcp",
    )

    @mcp.tool()
    def list_employees(department: str | None = None, limit: int = 50) -> list[dict]:
        """List employees from the synthetic SQLite fixture."""
        limit = max(1, min(limit, 100))
        sql = (
            "SELECT id, name, email, department, role, hire_date, salary_band "
            "FROM employees"
        )
        params: list[str | int] = []
        if department:
            sql += " WHERE department = ?"
            params.append(department)
        sql += " ORDER BY name LIMIT ?"
        params.append(limit)
        with _connect(query_db_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return _rows_to_dicts(rows)

    @mcp.tool()
    def list_projects(status: str | None = None, limit: int = 50) -> list[dict]:
        """List projects from the synthetic SQLite fixture."""
        limit = max(1, min(limit, 100))
        sql = (
            "SELECT id, name, owner_employee_id, status, budget_eur, start_date, end_date "
            "FROM projects"
        )
        params: list[str | int] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY name LIMIT ?"
        params.append(limit)
        with _connect(query_db_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return _rows_to_dicts(rows)

    @mcp.tool()
    def run_select(sql: str) -> list[dict]:
        """Execute a validated read-only SELECT query against the synthetic fixture."""
        _validate_select(sql)
        with _connect(query_db_path) as connection:
            rows = connection.execute(sql).fetchall()
        return _rows_to_dicts(rows)

    return mcp


def main() -> None:
    build_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
