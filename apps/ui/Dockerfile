FROM python:3.12-slim

WORKDIR /app

COPY apps/ui/pyproject.toml /app/pyproject.toml
COPY apps/ui/src /app/src

RUN pip install --no-cache-dir .

EXPOSE 8501

CMD ["streamlit", "run", "src/agentforge_ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
