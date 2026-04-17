FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY README.md /app/README.md
COPY apps/mcp_servers/github/pyproject.toml /app/apps/mcp_servers/github/pyproject.toml
COPY apps/mcp_servers/github/src /app/apps/mcp_servers/github/src
RUN uv sync --directory /app/apps/mcp_servers/github --no-dev

EXPOSE 8104

CMD ["uv", "run", "--directory", "/app/apps/mcp_servers/github", "github-mcp"]
