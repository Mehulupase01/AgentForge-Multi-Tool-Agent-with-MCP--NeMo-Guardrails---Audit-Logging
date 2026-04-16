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
- Phase 2 schema now includes `sessions`, `tasks`, `task_steps`, and append-only `audit_events`.

## Audit And Session Layer

- `sessions` is the top-level operator session record with lifecycle state and metadata.
- `tasks` and `task_steps` are present as Phase 2 placeholders so later orchestration phases can attach execution state without reshaping the persistence layer.
- `audit_events` stores the canonical JSON payload, payload hash, previous chain hash, and current chain hash for every recorded event.
- The control plane exposes `POST /api/v1/sessions`, `GET /api/v1/sessions`, `GET /api/v1/sessions/{id}`, `POST /api/v1/sessions/{id}/end`, `GET /api/v1/audit/events`, `GET /api/v1/audit/sessions/{id}/events`, and `GET /api/v1/audit/integrity`.
- Hash-chain integrity is verified by recomputing payload hashes and link continuity in sequence order, so payload tampering and row deletion are both detectable.

## Phase 1 Scope

Phase 1 establishes the workspace, API package, configuration model, logging, health endpoints, Alembic scaffolding, test harness, and container baseline that the later phases will build on.

## Phase 2 Scope

Phase 2 establishes the audit logging core, session APIs, shared response envelopes, and the tamper-evident hash chain that later orchestration, guardrails, approvals, and red-team phases will build on.
