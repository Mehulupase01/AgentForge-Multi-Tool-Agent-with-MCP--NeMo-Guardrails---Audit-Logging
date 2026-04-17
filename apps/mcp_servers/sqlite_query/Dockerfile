FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY README.md /app/README.md
COPY apps/mcp_servers/sqlite_query/pyproject.toml /app/apps/mcp_servers/sqlite_query/pyproject.toml
COPY apps/mcp_servers/sqlite_query/src /app/apps/mcp_servers/sqlite_query/src
RUN uv sync --directory /app/apps/mcp_servers/sqlite_query --no-dev

EXPOSE 8103

CMD ["uv", "run", "--directory", "/app/apps/mcp_servers/sqlite_query", "sqlite-query-mcp"]
