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
