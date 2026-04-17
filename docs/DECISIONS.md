# Decisions

## Seeded From Blueprint

- `D-001`: Use a modular monolith control plane plus sidecar MCP servers rather than pure microservices.
- `D-002`: Use LangGraph 0.2.61 for orchestration rather than CrewAI or AutoGen.
- `D-003`: Use NeMo Guardrails 0.11.0 plus Presidio for PII handling rather than alternative guardrail stacks.
- `D-004`: Use MCP `streamable_http` transport rather than stdio subprocess transport.
- `D-005`: Use an append-only `audit_events` table with a SHA-256 hash chain serialized at write time.
- `D-006`: Use `X-API-Key` single-user auth rather than JWT or OAuth for the demo control plane.

## Phase 1 Review Checklist

- No phase-level architectural changes were introduced.
- Runtime remains pinned to Python 3.12 in project metadata even though the host machine also has Python 3.13 installed.
- The Docker builder uses the repo-root workspace `uv.lock` plus `build-essential` so the pinned dependency graph can build reproducibly inside Linux containers.
- `numpy==1.26.4` is pinned explicitly to keep the `spacy 3.7.6` and `thinc` binary stack stable during container builds.

## Phase 2 Review Checklist

- No phase-level architectural changes were introduced; the implementation follows the blueprint's session/task/task_step/audit domain shape and public API surface.
- Audit chain serialization follows the blueprint decision exactly: `pg_advisory_xact_lock(99)` on PostgreSQL, with SQLite test serialization handled in-process so `test_audit_concurrent_writes` stays deterministic.
- `audit_events` remains append-only in application code. The code paths added in `agentforge.services.audit_service`, `agentforge.routers.sessions`, and `agentforge.routers.audit` only insert or read audit rows; direct `UPDATE` and `DELETE` operations exist only in test-only tamper simulations.
- The blueprint numbering gap is preserved intentionally: Phase 2 creates `001_foundation` and `004_audit_events`, while `002`, `003`, `005`, and `006` remain reserved for their future owning phases instead of introducing empty placeholder migrations.
- The documented demo key is normalized to `dev-key` so the blueprint's curl verification commands work without undocumented local overrides.

## Phase 3 Review Checklist

- No phase-level architectural changes were introduced; the implementation follows the blueprint's corpus metadata model, separate synthetic SQLite tool database, and CLI entrypoint requirements.
- `fixtures/synthetic.sqlite` remains separate from the control-plane database per decision `D-007`, so future `sqlite_query` MCP work can operate on an isolated read-only data plane.
- `corpus_service.reindex()` parses YAML frontmatter, excludes `README.md`, hashes full file content, counts tokens using whitespace split, and upserts on `filename`, which keeps the corpus row count aligned with the 53 generated fixture documents.
- The migration numbering gap remains explicit: `006_corpus.py` depends on `004_audit_events`, while `002`, `003`, and `005` stay reserved for their owning phases rather than placeholder migrations.
- The standalone Windows `sqlite3` shell is absent on this host, so local verification used `python -m sqlite3` to prove the generated row counts without changing the project stack.

## Phase 4 Review Checklist

- `D-013`: Upgrade the MCP SDK pin from `1.1.2` to `1.27.0`, and the explicit pydantic pin from `2.10.3` to `2.11.0`, because the originally pinned SDK did not expose the `FastMCP` and `streamable_http` APIs required by the blueprint's architecture. This preserves the blueprint's transport and sidecar model instead of changing the design.
- `D-014`: Use short-lived `streamable_http` sessions in `MCPClientPool` with cached server metadata instead of keeping long-lived sessions open. On this Windows host and SDK combination, long-lived teardown triggered cross-task cancel-scope errors during pytest cleanup.
- `D-015`: Docker verification is explicitly waived on this host by user instruction because Docker Desktop is broken locally and Bitdefender is interfering with process startup behavior. Phase 4 closure for this machine therefore relies on passing sidecar tests, passing API MCP integration tests, and live host-side process verification.
- No architectural changes were made to the tool surface: the four sidecars remain `file_search`, `web_fetch`, `sqlite_query`, and `github`, all exposed over `streamable_http` at `/mcp`.
- The GitHub MCP sidecar remains read-only and requires `GITHUB_TOKEN` at startup; Phase 4 now verifies that requirement with both unit coverage and live host startup.
