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

## Phase 5 Review Notes

- `D-016`: The Phase 5 LLM provider uses OpenRouter as the primary local execution path for live model runs, while still keeping compatibility with the blueprint's OpenAI client shape through the same `openai` SDK. The default OpenRouter model is `openrouter/free` because OpenRouter's official free-router docs state that it filters the current free pool by required capabilities such as tool calling and structured outputs, which is a better fit for the orchestrator's JSON-plan generation than pinning a single rotating free backend.
- `D-017`: Settings parsing now treats common deployment strings such as `DEBUG=release` or `DEBUG=production` as `False` instead of crashing the application at import time. This is an environment-hardening fix, not a config-surface change.
- `D-018`: The LangGraph implementation uses internal node identifiers `plan_node`, `next_step_node`, `execute_step_node`, `record_step_node`, and `finalize_node` because the library forbids node names that collide with state keys like `plan`.
- `D-019`: The Phase 5 migration `002_tool_and_llm_calls.py` depends on `006_corpus` in the live repo lineage so existing local databases can upgrade linearly from the already-shipped Phase 3 head. This preserves upgrade safety on the real branch even though the ideal numbered order in the blueprint assumes all intermediate phase migrations land later.
- `D-020`: Planner requests use OpenRouter structured outputs with `response_format`, provider `require_parameters=true`, and the `response-healing` plugin. This keeps the JSON plan contract reliable on the free-model path without changing the orchestrator architecture.
- `D-021`: `file_search.search_corpus` now applies a minimal singular/plural term expansion so natural queries like `transformers` match deterministic fixture documents titled with `transformer`.

## Phase 6 Review Notes

- `D-022`: The committed Phase 6 enforcement path is deterministic in Python through `GuardrailsRunner`. NeMo Guardrails config assets are present in the repo to preserve the blueprint shape, but the live blocking/redaction logic avoids making the verification suite depend on a second non-deterministic LLM judge.
- `D-023`: Presidio is used for PII detection, but placeholder replacement is performed in-process rather than through `AnonymizerEngine`. This keeps redacted output stable across versions while preserving the blueprint’s Presidio-based detection layer.
- `D-024`: The local spaCy model installation used a direct wheel URL through `uv pip install --python ...` because the repo `.venv` does not expose `pip`, and the standard `python -m spacy download ... --direct` path therefore fails on this host.
