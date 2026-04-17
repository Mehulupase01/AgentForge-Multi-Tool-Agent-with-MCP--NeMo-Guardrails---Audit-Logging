FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY README.md /app/README.md
COPY apps/mcp_servers/file_search/pyproject.toml /app/apps/mcp_servers/file_search/pyproject.toml
COPY apps/mcp_servers/file_search/src /app/apps/mcp_servers/file_search/src
RUN uv sync --directory /app/apps/mcp_servers/file_search --no-dev

EXPOSE 8101

CMD ["uv", "run", "--directory", "/app/apps/mcp_servers/file_search", "file-search-mcp"]
