from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./local.db"
    api_key: str = "dev-key-change-me"
    secret_key: str = ""
    api_port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False
    log_level: str = "INFO"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"

    mcp_file_search_url: str = "http://localhost:8101/mcp"
    mcp_web_fetch_url: str = "http://localhost:8102/mcp"
    mcp_sqlite_query_url: str = "http://localhost:8103/mcp"
    mcp_github_url: str = "http://localhost:8104/mcp"
    mcp_tool_allowlist_path: str = "src/agentforge/guardrails/config/tool_allowlist.yml"

    corpus_path: str = "fixtures/corpus"
    synthetic_db_path: str = "fixtures/synthetic.sqlite"
    github_token: str | None = None

    orchestrator_checkpoint_path: str = "runtime/orchestrator_checkpoints.sqlite"

    agentforge_api_url: str = "http://api:8000"
    agentforge_api_key: str = "dev-key-change-me"
    redteam_threshold_pct: float = 96.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
