# Phase 07: Human-in-the-Loop Approval

## Objective

Add the typed approval queue, deterministic risk classification, persistent LangGraph checkpoints, and resumable task execution.

## Delivered

- `003_approvals.py` adds the `approvals` table, the `risk_level` and `approval_decision` enums, and `tool_calls.approval_id`.
- `ApprovalService` classifies risky tool calls deterministically and owns the per-task wake queue used to resume paused runs.
- `AgentOrchestrator` now persists checkpoints through `AsyncSqliteSaver`, pauses on medium- and high-risk tool calls, and resumes after approval decisions.
- `/api/v1/approvals` now supports listing, fetching, and deciding approval requests.
- `POST /api/v1/tasks/{id}/resume` now signals checkpoint resumption explicitly.

## Risk Rules

- Read-only corpus, GitHub, and list-style SQLite tools are `LOW`.
- `web_fetch.fetch_url` becomes `MEDIUM` unless the host is in a static allowlist.
- `sqlite_query.run_select` becomes `MEDIUM` for salary joins, missing limits, or limits greater than 100.
- Write-like tool names are treated as `HIGH`.

## Verification

```powershell
$env:PYTHONPATH='src'
$env:DATABASE_URL='sqlite+aiosqlite:///./phase7_verify.sqlite'
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head

$env:DEBUG='false'
.\.venv\Scripts\python.exe -m pytest tests/test_approvals.py tests/test_orchestrator_hitl.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_agent_orchestrator.py -q
```

## Notes

- SQLite migrations use Alembic batch mode for the new `tool_calls.approval_id` foreign key.
- The in-memory SQLite approval tests include a short settle delay before polling because the background task and the HTTP reads share a single `StaticPool` connection in the test harness.
