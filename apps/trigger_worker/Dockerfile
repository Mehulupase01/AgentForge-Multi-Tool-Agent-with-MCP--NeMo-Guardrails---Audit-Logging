FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./pyproject.toml
COPY src ./src

RUN uv pip install --system .

EXPOSE 8105

CMD ["uvicorn", "trigger_worker.server:app", "--host", "0.0.0.0", "--port", "8105"]
