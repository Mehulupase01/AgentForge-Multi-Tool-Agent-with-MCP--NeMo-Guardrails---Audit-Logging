# Migration Guide: v1 to v2

## Overview

v2 is a branch-level upgrade from the original single-orchestrator AgentForge runtime to a supervised multi-agent system. The base control plane, audit chain, approvals, MCP sidecars, and Streamlit/CLI surfaces remain intact. This guide focuses on what existing v1 users need to add or verify.

## What Changes Functionally

| Area | v1 | v2 |
| --- | --- | --- |
| Orchestration | single orchestrator | supervisor graph with six roles |
| Recovery | checkpoint resume after approval | resume plus replay-safe recovery |
| Tool packaging | direct orchestrator-to-tool dispatch | skill-mediated dispatch with YAML policy |
| Review | human approval only | human approval plus Security Officer review |
| Triggering | manual task creation | manual + webhook + schedule driven task creation |
| Observability | task state and audit trail | task state, audit trail, cost, confidence, handoff analytics |
| Safety evaluation | v1 redteam suite | v1 + v2 redteam suites |

## Database Upgrade

Run the full Alembic head on the v2 branch:

```powershell
uv run --directory apps/api alembic upgrade head
```

This applies the v2 migrations:

- `007_multi_agent`
- `008_skills`
- `009_reviews`
- `010_triggers`
- `011_observability`

## New Environment Variables

Add these to your local `.env` if you are upgrading from a v1 environment file:

```env
CONFIDENCE_GATE_THRESHOLD=80.0
TRIGGER_WORKER_URL=http://trigger_worker:8105
TRIGGER_WORKER_INTERNAL_API_KEY=dev-key-change-me
GITHUB_WEBHOOK_SECRET=
GENERIC_WEBHOOK_SECRET=
OPENAI_PRICES_PATH=fixtures/pricing/openai_prices.yml
REPLAY_MAX_CHECKPOINT_AGE_HOURS=72
```

Notes:

- AgentForge stays `OpenRouter-first` on this branch.
- `OPENAI_PRICES_PATH` is still the configured env name because that is the contract used by the pricing loader, but the shipped fixture includes `openrouter/free` with zero-cost defaults.
- If you do not use GitHub or generic webhooks, the webhook secrets can remain empty.

## New Runtime Component

v2 adds one new sidecar:

- `apps/trigger_worker`

It hosts APScheduler-based trigger execution and calls the API back through the internal trigger endpoint.

Local start example:

```powershell
uv run --directory apps/trigger_worker uvicorn trigger_worker.server:app --app-dir src --host 0.0.0.0 --port 8105
```

## Skills Migration

v2 introduces YAML-backed skills. Existing v1 tool access still works through the orchestrator path, but the intended v2 flow is:

1. define or update skills under `apps/api/src/agentforge/skills/`
2. reload with `POST /api/v1/skills/reload`
3. verify policy keys stay within the closed schema

Do not treat skill files as arbitrary prompt templates. They are a runtime contract.

## API Surface Additions

New endpoints you can expect after upgrading:

- `GET /api/v1/agents`
- `GET /api/v1/agents/{role}/capabilities`
- `POST /api/v1/tasks/{id}/replay`
- `GET /api/v1/tasks/{id}/reviews`
- `GET /api/v1/tasks/{id}/agents`
- `GET /api/v1/skills`
- `GET /api/v1/skills/{id}`
- `POST /api/v1/skills/reload`
- trigger CRUD + webhook/internal fire endpoints
- `/api/v1/observability/*`

Task payloads also gain richer fields such as agent runs, reviews, cost summaries, and confidence summaries.

## Behavior Differences To Expect

- Task streams can now emit `agent_handoff`, `agent_retry`, `review_verdict`, `skill_invoked`, `cost_update`, `confidence_update`, and `task_replayed`.
- Some tasks that would previously complete may now pause because the confidence gate or Security Officer review path intervenes.
- Replay is intentionally conservative. Side-effectful work is not silently repeated.

## Verification After Upgrade

Recommended upgrade checks:

```powershell
uv run --directory apps/api pytest -v
uv run --directory apps/api pytest tests/test_supervisor_graph.py tests/test_self_healing.py tests/test_replay.py tests/test_skills_registry.py tests/test_security_officer.py tests/test_triggers.py tests/test_cost_tracker.py tests/test_confidence_scorer.py tests/test_confidence_gate.py -v
uv run --directory apps/api pytest tests/safety/test_redteam_suite.py tests/safety/test_redteam_v2.py -v
```

## Rollback Guidance

If you need to stay on v1 behavior, keep using the v1 branch or `main`. The v2 branch is additive but changes orchestration and operator expectations enough that it should be treated as a release upgrade, not a patch release.
