# AgentForge Working Memory

## Project Identity

- Project: `A3 AgentForge - Multi-Tool Agent with MCP, NeMo Guardrails & Audit Logging`
- Product shape: Enterprise-safe agentic AI with MCP tool servers, guardrails, HITL, and tamper-evident audit trail
- Repo mode: flagship, production-grade, phase-wise delivery
- Active branch: `main`
- Public repo: https://github.com/Mehulupase01/AgentForge-Multi-Tool-Agent-with-MCP--NeMo-Guardrails---Audit-Logging

## Current Commands

### Phase 1 verified

```powershell
uv sync --directory apps/api
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api pytest -v
uv run --directory apps/api uvicorn agentforge.main:app --host 0.0.0.0 --port 8000 --app-dir src
docker compose up -d --build
docker compose ps
docker compose down
```

### Verification Notes

- Host verification used Python `3.12.10` provisioned by `uv`, matching the blueprint's Python 3.12 runtime requirement despite the machine also having Python 3.13 installed.
- Local direct `uvicorn` verification was executed on port `8010` because port `8000` was already occupied by an unrelated local FastAPI service on this machine.
- Container verification succeeded on the documented port mapping `8000:8000`.

## Active Decisions

- Architecture: modular monolith FastAPI control plane + 4 MCP sidecars + Streamlit UI
- ORM: SQLAlchemy 2.0 async + Alembic
- Agent: LangGraph 0.2.61 with SqliteSaver checkpointer (HITL via interrupts)
- Tool protocol: MCP 1.1.2 over streamable_http
- Guardrails: NeMo Guardrails 0.11.0 + presidio for PII + custom injection detector + tool allowlist
- Audit: append-only `audit_events` with SHA-256 hash chain, integrity endpoint
- Auth: X-API-Key header, single-user demo
- DB: PostgreSQL 16 prod, SQLite in-memory tests
- Red-team threshold: >= 96% to pass CI; target 98%

## Current Execution Truth

- Blueprint: complete (local-only, untracked by user preference)
- Phase 1 (Foundation): complete and verified
- Phase 2 (Audit Logging Core): not started
- Phase 3 (Synthetic Data & Corpus): not started
- Phase 4 (MCP Tool Servers): not started
- Phase 5 (Agent Orchestrator): not started
- Phase 6 (Guardrails Layer): not started
- Phase 7 (Human-in-the-Loop Approval): not started
- Phase 8 (Red-Team Test Suite): not started
- Phase 9 (Streamlit UI + CLI): not started
- Phase 10 (Hardening & Release): not started

## Update Rule

Update this file after each verified phase closure together with:
- `docs/HANDOFF.md`
- `docs/PROGRESS.md`
- `docs/DECISIONS.md`
- `docs/architecture.md`
- `docs/verification.md`
