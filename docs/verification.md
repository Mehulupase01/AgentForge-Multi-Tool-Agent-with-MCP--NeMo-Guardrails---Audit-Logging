# Verification Log

## 2026-04-16 - Phase 1 Foundation

- `uv sync --directory apps/api`
  Result: passed. `uv` selected CPython `3.12.10` and created the project environment successfully.
- `uv run --directory apps/api alembic upgrade head`
  Result: passed. No migrations existed yet, so the upgrade was a no-op as expected.
- `uv run --directory apps/api pytest -v`
  Result: passed. `4/4` tests green.
- `uv run --directory apps/api uvicorn agentforge.main:app --host 0.0.0.0 --port 8000 --app-dir src`
  Result: host port `8000` was already occupied by an unrelated local service, so direct host verification was performed on `8010` instead.
- `curl http://localhost:8010/openapi.json`
  Result: passed. Returned the AgentForge OpenAPI document.
- `curl http://localhost:8010/api/v1/health/liveness`
  Result: passed. Returned `{"status":"ok"}`.
- `curl http://localhost:8010/api/v1/health/readiness`
  Result: passed. Returned `{"status":"ok","database":"ok","mcp_servers":{"file_search":"not_configured","web_fetch":"not_configured","sqlite_query":"not_configured","github":"not_configured"}}`.
- `docker compose up -d --build`
  Result: passed after fixing the builder image for the pinned dependency graph.
- `docker compose ps`
  Result: passed. `api` and `db` both reached healthy state.
- `curl http://localhost:8000/api/v1/health/liveness`
  Result: passed under Docker. Returned `{"status":"ok"}`.
- `curl http://localhost:8000/api/v1/health/readiness`
  Result: passed under Docker. Returned readiness `200` with database `ok`.
- `docker compose down`
  Result: passed. Stack shut down cleanly.

## 2026-04-16 - Phase 2 Audit Logging Core

- `uv run --directory apps/api alembic upgrade head`
  Result: passed. The SQLite dev database upgraded cleanly through `001_foundation` and `004_audit_events`.
- `uv run --directory apps/api pytest tests/test_sessions.py tests/test_audit.py tests/test_audit_chain.py -v`
  Result: passed. `6/6` tests green, including tamper detection, deletion detection, and 100-coroutine concurrent write verification.
- `uv run --directory apps/api uvicorn agentforge.main:app --host 0.0.0.0 --port 8000 --app-dir src`
  Result: host port `8000` was still occupied by an unrelated local service, so direct host verification was executed on `8011` instead.
- `curl -H "X-API-Key: dev-key" -X POST http://localhost:8011/api/v1/sessions -H "Content-Type: application/json" -d "{}"`
  Result: passed. Returned `{"id":"d76d0ba3-cc2a-45cc-9303-410f49cbbb96","user_id":"demo_user","status":"active","started_at":"2026-04-16T17:42:57.681222","ended_at":null,"metadata":{},"task_count":0,"tool_call_count":0,"approval_count":0}` against a fresh migrated SQLite database.
- `curl -H "X-API-Key: dev-key" http://localhost:8011/api/v1/audit/integrity`
  Result: passed. Returned `{"verified":true,"events_checked":1,"first_broken_sequence":null,"expected_chain_hash":null,"actual_chain_hash":null}` immediately after the fresh session creation.

## 2026-04-16 - Phase 3 Synthetic Data And Corpus

- `uv run --directory apps/api python -m agentforge.tools.generate_corpus`
  Result: passed. Generated 53 deterministic corpus documents plus `fixtures/corpus/README.md` under the repo-root fixture directory.
- `uv run --directory apps/api agentforge seed-synthetic --output fixtures/synthetic.sqlite`
  Result: passed. Created the generated SQLite fixture database with `employees=200`, `projects=30`, and `assignments=600`.
- `uv run --directory apps/api alembic upgrade head`
  Result: passed. The SQLite dev database upgraded cleanly through `006_corpus`.
- `uv run --directory apps/api agentforge ingest-corpus`
  Result: passed. Indexed 53 corpus documents into `corpus_documents`.
- `uv run --directory apps/api pytest tests/test_corpus.py -v`
  Result: passed. `5/5` tests green, covering synthetic DB creation, deterministic corpus generation, idempotent reindex, change detection, and paginated document listing.
- `python -m sqlite3 fixtures/synthetic.sqlite "SELECT COUNT(*) FROM employees;"`
  Result: passed on this Windows host as the local equivalent of the missing standalone `sqlite3` shell. Returned `(200,)`.
- `python -m sqlite3 fixtures/synthetic.sqlite "SELECT COUNT(*) FROM projects;"`
  Result: passed on this Windows host as the local equivalent of the missing standalone `sqlite3` shell. Returned `(30,)`.
- `curl -H "X-API-Key: dev-key" -X POST http://localhost:8012/api/v1/corpus/reindex`
  Result: passed. Returned `{"indexed":0,"skipped_unchanged":53,"duration_ms":288}` against the already-generated corpus.
- `curl -H "X-API-Key: dev-key" http://localhost:8012/api/v1/corpus/documents?page=1&per_page=5`
  Result: passed. Returned a paginated envelope with `meta.total=53` and the first 5 corpus documents. Local host verification used port `8012` because port `8000` is occupied by an unrelated local service on this machine.

## 2026-04-17 - Phase 4 MCP Tool Servers

- `.\.venv\Scripts\python.exe -m pytest apps/mcp_servers/file_search/tests apps/mcp_servers/web_fetch/tests apps/mcp_servers/sqlite_query/tests apps/mcp_servers/github/tests -q`
  Result: passed. `8/8` sidecar unit tests green, covering file search, allowlist enforcement, read-only SQLite query enforcement, and GitHub token startup requirements.
- `.\.venv\Scripts\python.exe -m pytest apps/api/tests/test_health.py apps/api/tests/test_mcp_client_pool.py -q`
  Result: passed. `10/10` control-plane tests green, covering MCP discovery, tool listing, tool dispatch, readiness reporting, and unreachable-sidecar degradation behavior.
- Live host-side process verification:
  Result: passed. All four sidecars were started as real background processes on ports `8101` through `8104`, the API was started on `8013`, and `GET /api/v1/health/readiness` returned `{"status":"ok","database":"ok","mcp_servers":{"file_search":"ok","web_fetch":"ok","sqlite_query":"ok","github":"ok"}}`.
- `curl -H "X-API-Key: dev-key" http://127.0.0.1:8013/api/v1/mcp/servers`
  Result: passed. Returned four MCP servers with statuses `ok` and tool counts `2`, `3`, `3`, and `3`.
- `curl -H "X-API-Key: dev-key" http://127.0.0.1:8013/api/v1/mcp/servers/file_search/tools`
  Result: passed. Returned the expected `search_corpus` and `read_document` descriptors with JSON input schemas.
- `docker compose -f ops/docker/compose.sidecars.yml up -d --build`
  Result: skipped on this host by explicit user instruction. Docker Desktop is currently broken locally and Bitdefender is interfering with some commands, so Docker verification is intentionally deferred until the local environment is repaired.

## 2026-04-17 - Phase 5 Agent Orchestrator

- `python -m alembic -c alembic.ini upgrade head`
  Result: passed from `apps/api` with `PYTHONPATH=src`. The local SQLite dev database upgraded cleanly through `002_tool_and_llm_calls`.
- `python -m pytest apps/mcp_servers/file_search/tests -q`
  Result: passed. `3/3` tests green, including the added singular/plural search coverage for natural corpus queries.
- `python -m pytest apps/api/tests/test_health.py apps/api/tests/test_mcp_client_pool.py apps/api/tests/test_agent_orchestrator.py -q`
  Result: passed. `14/14` tests green, confirming no orchestrator regressions against the prior health and MCP integration surfaces.
- Live host-side smoke test
  Result: passed. All four sidecars were started as real background processes on ports `8101` through `8104`, the API was started on `8014`, and `POST /api/v1/sessions/{id}/tasks` completed end-to-end against OpenRouter with the prompt `Find 3 articles about transformers in the corpus and summarize them.` The task finished `completed` with a non-empty `final_response` summarizing `01-transformer-architectures-in-practice.md`.

## 2026-04-17 - Phase 6 Guardrails Layer

- `uv pip install --python .venv\\Scripts\\python.exe https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl`
  Result: passed. This was the local equivalent of the blueprint's `python -m spacy download ... --direct` step because the repo `.venv` does not expose `pip` on this Windows host.
- `python -m pytest apps/api/tests/test_guardrails_pii.py apps/api/tests/test_guardrails_injection.py apps/api/tests/test_guardrails_topic.py apps/api/tests/test_guardrails_tool_allowlist.py apps/api/tests/test_agent_orchestrator.py -q`
  Result: passed. `17/17` tests green, covering PII redaction, injection blocking, topic gating, allowlist enforcement, orchestrator input blocking, orchestrator redaction logging, and disallowed-tool skipping.

## 2026-04-17 - Phase 7 Human-in-the-Loop Approval

- `DATABASE_URL=sqlite+aiosqlite:///./phase7_verify.sqlite python -m alembic -c alembic.ini upgrade head`
  Result: passed from `apps/api` with `PYTHONPATH=src`. A fresh temporary SQLite database upgraded cleanly through `003_approvals`, including the batch-mode `tool_calls.approval_id` foreign key change.
- `python -m pytest tests/test_approvals.py tests/test_orchestrator_hitl.py -v`
  Result: passed. `8/8` tests green, covering pending approval listing, approval and rejection decisions, idempotent decisions, medium-risk host gating, low-risk bypass, approval audit lifecycle, and explicit resume-endpoint orchestration.
- `python -m pytest tests/test_agent_orchestrator.py -q`
  Result: passed. `7/7` orchestrator regression tests green after the Phase 7 interrupt/resume changes.

## 2026-04-17 - Phase 8 Red-Team Test Suite

- Host-side MCP startup on ports `8101` through `8104`
  Result: passed. All four sidecars were launched as real background processes from the repo `.venv`, and each answered HTTP requests on its configured `/mcp` endpoint.
- `DATABASE_URL=sqlite+aiosqlite:///./phase8_cli.sqlite python -m alembic -c alembic.ini upgrade head`
  Result: passed from `apps/api` with `PYTHONPATH=src`. A fresh temporary SQLite database upgraded cleanly through `005_redteam`.
- `agentforge redteam-run`
  Result: passed. The final local run persisted one `redteam_runs` row plus `50` `redteam_results` rows, wrote `apps/api/redteam-report.xml`, and finished at `50/50` passed (`100.00%` compliance).
- `python -m pytest tests/safety/test_redteam_suite.py -v`
  Result: passed. `4/4` tests green, covering scenario validation, persisted results, threshold enforcement, and category filtering.
- Docker compose sidecar startup
  Result: skipped on this host by explicit user instruction. Docker Desktop remains broken locally and Bitdefender is interfering with some commands, so Phase 8 host verification relied on direct sidecar processes instead.

## 2026-04-17 - Phase 9 Streamlit UI And CLI

- `uv pip install --python .venv\\Scripts\\python.exe streamlit==1.41.1 pandas==2.2.3`
  Result: passed. The repo `.venv` now includes the pinned Streamlit and pandas dependencies required by the new UI package.
- `python -m pytest apps/api/tests/test_sse_compat.py apps/ui/tests/test_imports.py -v`
  Result: passed. `3/3` tests green, covering SSE parser compatibility for both clients, CLI subprocess streaming against a mock-backed API server, and Streamlit page import smoke coverage.
- Mock-backed host operator flow
  Result: passed. A local uvicorn harness with the existing mock orchestrator stack served the API on an ephemeral port; `agentforge session new`, `agentforge task run "Find transformer content and summarize it."`, and `agentforge audit verify` all completed successfully against that server.
- Headless Streamlit boot
  Result: passed. `streamlit run apps/ui/src/agentforge_ui/app.py --server.headless=true` served HTTP `200` on an ephemeral local port when pointed at the same mock-backed API harness.

## 2026-04-17 - Phase 10 Hardening And Release

- `uvx ruff check apps`
  Result: passed. All application packages, tests, and client code are lint-clean after the final release hardening sweep.
- `python -m pytest tests -q`
  Result: passed from `apps/api` with `PYTHONPATH=src`. The full API test suite finished `52 passed`, covering health, sessions, audit, corpus, MCP integration, orchestrator, guardrails, approvals, red-team, and SSE compatibility.
- `python -m pytest apps/mcp_servers/file_search/tests apps/mcp_servers/web_fetch/tests apps/mcp_servers/sqlite_query/tests apps/mcp_servers/github/tests apps/ui/tests/test_imports.py -q`
  Result: passed. `10/10` non-API package tests green across all four sidecars plus the Streamlit import smoke.
- Copied-working-tree release smoke
  Result: passed. A clean temp copy of the current working tree was created without `.git`, `.venv`, or the local-only blueprint files; `.env` was created from `.env.example`; a fresh SQLite URL `sqlite+aiosqlite:///./release_smoke.sqlite` was used; then `uv sync --directory apps/api`, `alembic upgrade head`, corpus generation, synthetic DB generation, corpus ingestion, and `pytest tests/test_health.py tests/test_corpus.py -q` all succeeded with `10/10` tests green.
- Docker compose full-stack startup
  Result: intentionally skipped on this host by explicit user instruction. Docker Desktop and Bitdefender remain broken locally, so Phase 10 release verification relies on host-side checks instead of container startup on this machine.
