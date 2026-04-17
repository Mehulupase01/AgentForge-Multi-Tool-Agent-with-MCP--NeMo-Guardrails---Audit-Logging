FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY apps/mcp_servers/file_search/pyproject.toml ./pyproject.toml
COPY apps/mcp_servers/file_search/src ./src
RUN uv sync --no-dev

EXPOSE 8101

CMD ["uv", "run", "file-search-mcp"]
