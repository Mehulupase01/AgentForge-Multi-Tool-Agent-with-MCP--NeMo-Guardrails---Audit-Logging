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
