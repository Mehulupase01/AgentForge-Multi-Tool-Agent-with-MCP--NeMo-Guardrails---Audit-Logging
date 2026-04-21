from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./local.db"
    api_key: str = "dev-key"
    secret_key: str = ""
    api_port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False
    log_level: str = "INFO"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openrouter/free"

    mcp_file_search_url: str = "http://localhost:8101/mcp"
    mcp_web_fetch_url: str = "http://localhost:8102/mcp"
    mcp_sqlite_query_url: str = "http://localhost:8103/mcp"
    mcp_github_url: str = "http://localhost:8104/mcp"
    mcp_tool_allowlist_path: str = "src/agentforge/guardrails/config/tool_allowlist.yml"

    corpus_path: str = "fixtures/corpus"
    synthetic_db_path: str = "fixtures/synthetic.sqlite"
    skills_path: str = "apps/api/src/agentforge/skills"
    github_token: str | None = None
    github_webhook_secret: str | None = None

    orchestrator_checkpoint_path: str = "runtime/orchestrator_checkpoints.sqlite"
    replay_max_checkpoint_age_hours: int = 72
    trigger_worker_url: str | None = None
    confidence_gate_threshold: float = 80.0
    openai_prices_path: str = "fixtures/pricing/openai_prices.yml"

    agentforge_api_url: str = "http://api:8000"
    agentforge_api_key: str = "dev-key"
    redteam_threshold_pct: float = 96.0

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return value

    @field_validator("confidence_gate_threshold")
    @classmethod
    def validate_confidence_gate_threshold(cls, value: float) -> float:
        if not 0.0 <= value <= 100.0:
            raise ValueError("CONFIDENCE_GATE_THRESHOLD must be between 0 and 100.")
        return value

    @property
    def openai_prices_path_resolved(self) -> Path:
        path = Path(self.openai_prices_path)
        return path if path.is_absolute() else Path(__file__).resolve().parents[4] / path

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
