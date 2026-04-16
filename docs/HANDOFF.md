# Handoff

## Current State

- Phase 2 is complete and verified locally.
- The repo now includes the Phase 1 foundation plus the Phase 2 session/task/audit domain models, migrations, session and audit routers, shared envelope/error schemas, and the tamper-evident SHA-256 audit chain service.

## Next Phase

- Phase 3: Synthetic Data & Corpus

## Resume Notes

- Run `uv sync --directory apps/api` before local work.
- Run `uv run --directory apps/api alembic upgrade head` before starting the API.
- If `uv sync` is run on this Windows host, ensure `C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64` is on `PATH` so the transitive `annoy` build can find `rc.exe`.
- Local host verification for both Phase 1 and Phase 2 used alternate ports because host port `8000` is occupied by an unrelated local FastAPI service on this machine.
- Phase 2 intentionally created only `001_foundation` and `004_audit_events`; the numbered gaps remain for their owning future phases per the blueprint's "no empty placeholder migration" rule.
- Application code must continue treating `audit_events` as append-only: no `UPDATE` or `DELETE` paths should be introduced outside test-only tamper checks.
- The only intentional untracked files are the local blueprint artifacts kept out of git by user instruction.
