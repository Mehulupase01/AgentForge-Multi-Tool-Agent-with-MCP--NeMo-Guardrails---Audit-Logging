FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir uv

WORKDIR /app

COPY apps/mcp_servers/web_fetch/pyproject.toml ./pyproject.toml
COPY apps/mcp_servers/web_fetch/src ./src
RUN uv sync --no-dev

EXPOSE 8102

CMD ["uv", "run", "web-fetch-mcp"]
