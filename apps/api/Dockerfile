FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.5.11
COPY pyproject.toml uv.lock /app/
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY apps/api/alembic /app/apps/api/alembic
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
RUN uv sync --frozen --no-dev --package agentforge-api
RUN .venv/bin/python -m ensurepip && .venv/bin/python -m spacy download en_core_web_sm-3.7.1 --direct

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY apps/api/src /app/apps/api/src
COPY apps/api/alembic /app/apps/api/alembic
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/apps/api/src
WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "agentforge.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
