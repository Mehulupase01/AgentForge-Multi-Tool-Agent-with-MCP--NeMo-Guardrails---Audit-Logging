# Architecture Summary

## System Shape

AgentForge uses a modular monolith FastAPI control plane that owns orchestration, audit, approvals, persistence, and guardrail integration. Tool execution is isolated into four MCP sidecars, while Streamlit and CLI remain thin clients over the HTTP API.

## Core Components

- FastAPI control plane: routing, auth, validation, SSE streaming, and shared service composition.
- Agent orchestrator: LangGraph plan-execute workflow with persistence and later interrupt/resume support.
- Guardrails runner: NeMo Guardrails plus PII redaction and tool allowlist enforcement.
- Audit service: append-only SHA-256 hash chain for tamper-evident event history.
- Approval service: typed approval queue and resumable human-in-the-loop checkpoints.
- MCP sidecars: `file_search`, `web_fetch`, `sqlite_query`, and `github`.
- Clients: Streamlit UI and Click CLI for operators.

## Persistence Model

- Production database: PostgreSQL 16.
- Development and tests: SQLite via `aiosqlite`.
- Alembic manages schema evolution from the API package.

## Phase 1 Scope

Phase 1 establishes the workspace, API package, configuration model, logging, health endpoints, Alembic scaffolding, test harness, and container baseline that the later phases will build on.
