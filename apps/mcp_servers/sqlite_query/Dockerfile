FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY apps/mcp_servers/sqlite_query/pyproject.toml ./pyproject.toml
COPY apps/mcp_servers/sqlite_query/src ./src
RUN uv sync --no-dev

EXPOSE 8103

CMD ["uv", "run", "sqlite-query-mcp"]
