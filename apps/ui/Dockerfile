FROM python:3.12-slim

WORKDIR /app

COPY README.md /app/README.md
COPY apps/ui/pyproject.toml /app/apps/ui/pyproject.toml
COPY apps/ui/src /app/apps/ui/src

RUN pip install --no-cache-dir /app/apps/ui

EXPOSE 8501

CMD ["streamlit", "run", "/app/apps/ui/src/agentforge_ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
