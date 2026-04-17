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

### Phase 2 verified

```powershell
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api pytest tests/test_sessions.py tests/test_audit.py tests/test_audit_chain.py -v
uv run --directory apps/api uvicorn agentforge.main:app --host 0.0.0.0 --port 8000 --app-dir src
curl -H "X-API-Key: dev-key" -X POST http://localhost:8000/api/v1/sessions -H "Content-Type: application/json" -d "{}"
curl -H "X-API-Key: dev-key" http://localhost:8000/api/v1/audit/integrity
```

### Phase 3 verified

```powershell
uv run --directory apps/api python -m agentforge.tools.generate_corpus
uv run --directory apps/api agentforge seed-synthetic --output fixtures/synthetic.sqlite
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api agentforge ingest-corpus
uv run --directory apps/api pytest tests/test_corpus.py -v
python -m sqlite3 fixtures/synthetic.sqlite "SELECT COUNT(*) FROM employees;"
python -m sqlite3 fixtures/synthetic.sqlite "SELECT COUNT(*) FROM projects;"
```

### Phase 4 verified

```powershell
.\.venv\Scripts\python.exe -m pytest apps/mcp_servers/file_search/tests apps/mcp_servers/web_fetch/tests apps/mcp_servers/sqlite_query/tests apps/mcp_servers/github/tests -q
.\.venv\Scripts\python.exe -m pytest apps/api/tests/test_health.py apps/api/tests/test_mcp_client_pool.py -q
```

### Phase 5 verified

```powershell
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest apps/mcp_servers/file_search/tests -q
.\.venv\Scripts\python.exe -m pytest tests/test_health.py tests/test_mcp_client_pool.py tests/test_agent_orchestrator.py -q
```

### Phase 6 verified

```powershell
uv pip install --python .\.venv\Scripts\python.exe https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
.\.venv\Scripts\python.exe -m pytest tests/test_guardrails_pii.py tests/test_guardrails_injection.py tests/test_guardrails_topic.py tests/test_guardrails_tool_allowlist.py tests/test_agent_orchestrator.py -q
```

### Phase 7 verified

```powershell
$env:PYTHONPATH='src'; $env:DATABASE_URL='sqlite+aiosqlite:///./phase7_verify.sqlite'; .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
$env:PYTHONPATH='src'; $env:DEBUG='false'; .\.venv\Scripts\python.exe -m pytest tests/test_approvals.py tests/test_orchestrator_hitl.py -v
$env:PYTHONPATH='src'; $env:DEBUG='false'; .\.venv\Scripts\python.exe -m pytest tests/test_agent_orchestrator.py -q
```

### Phase 8 verified

```powershell
$env:PYTHONPATH='src'; $env:DATABASE_URL='sqlite+aiosqlite:///./phase8_cli.sqlite'; .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
$env:PYTHONPATH='src'; $env:DEBUG='false'; .\.venv\Scripts\agentforge.exe redteam-run
$env:PYTHONPATH='src'; $env:DEBUG='false'; .\.venv\Scripts\python.exe -m pytest tests/safety/test_redteam_suite.py -v
```

### Phase 9 verified

```powershell
uv pip install --python .\.venv\Scripts\python.exe streamlit==1.41.1 pandas==2.2.3
$env:PYTHONPATH='D:\Mehul-Projects\AgentForge- Multi-Tool Agent with MCP, NeMo Guardrails & Audit Logging\apps\api\src'; $env:DEBUG='false'; .\.venv\Scripts\python.exe -m pytest apps/api/tests/test_sse_compat.py apps/ui/tests/test_imports.py -v
```

### Phase 10 verified

```powershell
uvx ruff check apps
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest apps/mcp_servers/file_search/tests apps/mcp_servers/web_fetch/tests apps/mcp_servers/sqlite_query/tests apps/mcp_servers/github/tests apps/ui/tests/test_imports.py -q
```

Fresh working-tree smoke used a copied clean temp checkout plus a fresh SQLite URL:

```powershell
copy .env.example .env
uv sync --directory apps/api
$env:DATABASE_URL='sqlite+aiosqlite:///./release_smoke.sqlite'
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api python -m agentforge.tools.generate_corpus
uv run --directory apps/api agentforge seed-synthetic --output fixtures/synthetic.sqlite
uv run --directory apps/api agentforge ingest-corpus
uv run --directory apps/api pytest tests/test_health.py tests/test_corpus.py -q
```

### Verification Notes

- Host verification used Python `3.12.10` provisioned by `uv`, matching the blueprint's Python 3.12 runtime requirement despite the machine also having Python 3.13 installed.
- Local direct `uvicorn` verification was executed on port `8010` because port `8000` was already occupied by an unrelated local FastAPI service on this machine.
- Container verification succeeded on the documented port mapping `8000:8000`.
- Phase 2 local host verification was executed on port `8011` for the same reason: host port `8000` is still occupied by an unrelated local FastAPI service on this machine.
- The documented demo API key is `dev-key`, and both `Settings.api_key` and `.env.example` now match the blueprint so the curl commands work as written.
- This Windows host does not have a standalone `sqlite3` shell on `PATH`, so Phase 3 row-count verification used the standard-library CLI entrypoint `python -m sqlite3` as the local equivalent.
- Phase 3 local host verification was executed on port `8012` because host port `8000` is still occupied by an unrelated local FastAPI service on this machine.
- The project virtualenv was rebuilt on CPython `3.12.13` during Phase 4 because the previous Windows Store-backed 3.12 shim had gone stale. The repo-root `.venv` is now the reliable local interpreter.
- `uv sync --directory apps/api` is currently unreliable on this Windows host because the already-pinned `nemoguardrails` dependency chain builds `annoy`, which needs `rc.exe`. Phase 4 local verification therefore used targeted installs into the repo `.venv` plus direct `python -m pytest` invocations.
- Phase 4 local live verification used port `8013` for the API because host port `8000` remains occupied by an unrelated local FastAPI service on this machine.
- Docker verification for Phase 4 is intentionally skipped on this host by explicit user instruction because Docker Desktop is currently broken locally and Bitdefender is interfering with some process startup behavior.
- Phase 5 local live verification used port `8014` for the API because host port `8000` remains occupied by an unrelated local FastAPI service on this machine.
- The repo `.venv` does not expose `pip`, so the local Phase 6 spaCy model install used a direct `uv pip install --python ... <wheel-url>` invocation instead of `python -m spacy download ... --direct`.
- The Phase 7 Alembic verification used a fresh temporary SQLite URL (`phase7_verify.sqlite`) so the full upgrade path could be validated from a clean database without relying on the existing local dev DB state.
- The approval and HITL tests use short initial delays before polling the API because the blueprint's in-memory SQLite test configuration runs through a single shared connection; without that settle window, concurrent read polling can starve the background approval write on this Windows host.
- Phase 8 local verification used host-launched MCP sidecars on ports `8101` through `8104`, but the final 50-scenario suite was intentionally fully adversarial and guardrail-blocked at task intake so it stayed stable under OpenRouter free-tier daily request limits.
- The benign PII-redaction path remains covered by the dedicated Phase 6 guardrail suites; Phase 8 now focuses purely on adversarial prompt injection, exfiltration, jailbreak, tool-abuse, goal-hijack, and PII leak attempts.
- Phase 9 local verification used a mock-backed host API harness for the CLI streaming and audit commands because the real-model path is currently quota-limited on this OpenRouter free-tier key. The UI itself was also verified headlessly by serving Streamlit and confirming HTTP `200` from the home page.
- Phase 10 adds real GitHub Actions workflows under `.github/workflows` while keeping the blueprint-shaped copies under `ops/github/workflows`. GitHub only executes workflows from the root `.github/workflows` path, so both locations are intentionally kept in sync.
- Phase 10 local release verification uses a copied clean working tree plus a fresh SQLite URL for the quickstart smoke. A plain local `git clone` was not sufficient before commit because it only reflected committed history and would miss the current release edits.
- Docker verification remains intentionally skipped on this host by explicit user instruction. Phase 10 therefore closes on host-side lint, host-side full pytest coverage, host-side sidecar/UI suites, and a copied-working-tree quickstart smoke instead of container startup on this machine.

## Active Decisions

- Architecture: modular monolith FastAPI control plane + 4 MCP sidecars + Streamlit UI
- ORM: SQLAlchemy 2.0 async + Alembic
- Agent: LangGraph 0.2.61 with SqliteSaver checkpointer (HITL via interrupts)
- Tool protocol: MCP 1.27.0 over streamable_http to preserve the blueprint's intended `FastMCP` + `streamable_http` architecture after the pinned 1.1.2 API drift was confirmed locally
- Guardrails: NeMo Guardrails 0.11.0 + presidio for PII + custom injection detector + tool allowlist
- Audit: append-only `audit_events` with SHA-256 hash chain, integrity endpoint
- Auth: X-API-Key header, single-user demo
- DB: PostgreSQL 16 prod, SQLite in-memory tests
- Red-team threshold: >= 96% to pass CI; target 98%
- Audit chain writes are serialized with `pg_advisory_xact_lock(99)` on PostgreSQL and an async process-local lock in SQLite-backed tests to keep `sequence` monotonic under concurrent writes.
- Fixture strategy: keep `fixtures/synthetic.sqlite` as a separate generated SQLite tool database, and keep the deterministic markdown corpus in tracked repo-root `fixtures/corpus/`.
- MCP client connections are short-lived per operation with cached tool metadata. This avoids cross-task shutdown issues seen with long-lived `streamable_http` sessions on this Windows host while preserving the same public API behavior.
- OpenRouter is the primary live-model path. The default model is `openrouter/free`, and planner requests enforce structured JSON output plus `require_parameters=true` so the free router selects only providers that support the JSON plan contract.
- `file_search.search_corpus` now applies a lightweight singular/plural term expansion so natural operator queries like `transformers` still match fixture documents containing `transformer`.
- Guardrails are enforced deterministically in Python through `GuardrailsRunner`, with Presidio-backed PII detection, injection heuristics, topic gating, output redaction, and a YAML-backed MCP tool allowlist.
- Phase 10 hardening adds the public release surface: `AGENTS.md`, `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/deployment.md`, the full stack compose definition, a flagship README, and real GitHub Actions workflow entrypoints.

## Current Execution Truth

- Blueprint: complete (local-only, untracked by user preference)
- Phase 1 (Foundation): complete and verified
- Phase 2 (Audit Logging Core): complete and verified
- Phase 3 (Synthetic Data & Corpus): complete and verified
- Phase 4 (MCP Tool Servers): complete and verified locally, with Docker verification explicitly waived by user instruction on this machine
- Phase 5 (Agent Orchestrator): complete and verified
- Phase 6 (Guardrails Layer): complete and verified
- Phase 7 (Human-in-the-Loop Approval): complete and verified
- Phase 8 (Red-Team Test Suite): complete and verified
- Phase 9 (Streamlit UI + CLI): complete and verified
- Phase 10 (Hardening & Release): complete and verified locally, with Docker verification explicitly waived on this host by user instruction

## Update Rule

Update this file after each verified phase closure together with:
- `docs/HANDOFF.md`
- `docs/PROGRESS.md`
- `docs/DECISIONS.md`
- `docs/architecture.md`
- `docs/verification.md`
