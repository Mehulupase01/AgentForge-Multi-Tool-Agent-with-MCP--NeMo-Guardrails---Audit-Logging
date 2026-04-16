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
