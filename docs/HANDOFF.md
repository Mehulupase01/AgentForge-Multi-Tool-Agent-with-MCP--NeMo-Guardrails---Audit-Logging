# Handoff

## Current State

- Phase 4 is complete and verified locally.
- Phase 5 is complete and verified locally.
- Phase 6 is complete and verified locally.
- The repo now includes the Phase 1 foundation, the Phase 2 audit core, the Phase 3 corpus/synthetic-data layer, the Phase 4 MCP server stack, the Phase 5 orchestrator layer, and the Phase 6 guardrails layer: deterministic guardrail enforcement, PII redaction, injection blocking, topic gating, tool allowlists, guardrail audit events, and guardrail-aware orchestrator tests.

## Next Phase

- Phase 7: Human-in-the-Loop Approval

## Resume Notes

- Run `uv sync --directory apps/api` before local work.
- Run `uv run --directory apps/api alembic upgrade head` before starting the API.
- If `uv sync` is run on this Windows host, ensure `C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64` is on `PATH` so the transitive `annoy` build can find `rc.exe`.
- Local host verification for both Phase 1 and Phase 2 used alternate ports because host port `8000` is occupied by an unrelated local FastAPI service on this machine.
- Phase 2 intentionally created only `001_foundation` and `004_audit_events`; the numbered gaps remain for their owning future phases per the blueprint's "no empty placeholder migration" rule.
- Application code must continue treating `audit_events` as append-only: no `UPDATE` or `DELETE` paths should be introduced outside test-only tamper checks.
- Phase 3 added `006_corpus.py` directly on top of `004_audit_events`; the numbering gaps `002`, `003`, and `005` are still intentionally reserved for future owning phases instead of placeholder migrations.
- The repo-root `fixtures/corpus/` directory now contains the tracked README plus 53 generated corpus documents; `fixtures/synthetic.sqlite` is generated locally and remains gitignored.
- This host does not expose a standalone `sqlite3` shell on `PATH`; local row-count verification used `python -m sqlite3` successfully.
- `GITHUB_TOKEN` is now present locally in the ignored `.env` and the GitHub MCP sidecar starts correctly with it.
- The repo-root `.venv` was rebuilt on CPython `3.12.13` during Phase 4 and is the reliable local interpreter for further work.
- Phase 4 used `mcp==1.27.0` plus `pydantic==2.11.0` because the blueprint pin `mcp==1.1.2` did not expose the `FastMCP` + `streamable_http` APIs required by the blueprint architecture.
- Phase 4 local verification passed via pytest and live host-side sidecar/API startup. Docker verification is intentionally skipped on this machine by explicit user instruction because Docker Desktop is currently broken locally and Bitdefender is interfering with some commands.
- `uv sync --directory apps/api` is still unreliable on this Windows host because the already-pinned `nemoguardrails` chain builds `annoy`; if that blocks future phases, continue with targeted `.venv` installs or fix the Windows SDK/toolchain first.
- Phase 5 added `002_tool_and_llm_calls.py`, `ToolCall` and `LLMCall` models, the task router, the LangGraph orchestrator, the per-task SSE event bus, and the thin LLM provider wrapper.
- Phase 5 verification passed with:
  - `python -m alembic -c alembic.ini upgrade head`
  - `python -m pytest apps/mcp_servers/file_search/tests -q`
  - `python -m pytest apps/api/tests/test_health.py apps/api/tests/test_mcp_client_pool.py apps/api/tests/test_agent_orchestrator.py -q`
  - a live host-side smoke run on port `8014` with all four sidecars plus the API, using OpenRouter and the prompt `Find 3 articles about transformers in the corpus and summarize them.`
- The successful live smoke completed with a non-empty `final_response` summarizing `01-transformer-architectures-in-practice.md`.
- Phase 6 verification passed with:
  - a local equivalent of the blueprint spaCy install step using `uv pip install --python .venv\\Scripts\\python.exe <en_core_web_sm wheel URL>` because the repo `.venv` does not expose `pip`
  - `python -m pytest apps/api/tests/test_guardrails_pii.py apps/api/tests/test_guardrails_injection.py apps/api/tests/test_guardrails_topic.py apps/api/tests/test_guardrails_tool_allowlist.py apps/api/tests/test_agent_orchestrator.py -q`
- The guardrails layer now returns `400 GUARDRAIL_BLOCKED` for blocked task intake, persists `guardrail_block` task steps, and records the new `guardrail.*` audit events required by the blueprint.
- The only intentional untracked files are the local blueprint artifacts kept out of git by user instruction.
