# Handoff

## Current State

- Phase 3 is complete and verified locally.
- The repo now includes the Phase 1 foundation, the Phase 2 audit core, and the Phase 3 corpus/synthetic-data layer: `corpus_documents`, corpus reindex/list APIs, the deterministic 53-document markdown corpus, the synthetic SQLite seed command, and the `agentforge` Click CLI entrypoints for corpus ingest and synthetic seeding.

## Next Phase

- Phase 4: MCP Tool Servers

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
- Phase 4 is blocked until `GITHUB_TOKEN` is available, per the blueprint's required environment contract for the GitHub MCP sidecar.
- The only intentional untracked files are the local blueprint artifacts kept out of git by user instruction.
