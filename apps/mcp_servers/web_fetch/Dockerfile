FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY README.md /app/README.md
COPY apps/mcp_servers/web_fetch/pyproject.toml /app/apps/mcp_servers/web_fetch/pyproject.toml
COPY apps/mcp_servers/web_fetch/src /app/apps/mcp_servers/web_fetch/src
RUN uv sync --directory /app/apps/mcp_servers/web_fetch --no-dev

EXPOSE 8102

CMD ["uv", "run", "--directory", "/app/apps/mcp_servers/web_fetch", "web-fetch-mcp"]
