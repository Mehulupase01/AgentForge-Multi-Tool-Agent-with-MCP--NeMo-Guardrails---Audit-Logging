# Deployment

## Stack

- `api`: FastAPI control plane
- `db`: PostgreSQL 16
- `file_search`, `web_fetch`, `sqlite_query`, `github`: MCP sidecars
- `ui`: Streamlit operator interface

## Compose Layout

- Full stack definition: `ops/docker/compose.full.yml`
- Root shortcut: `docker-compose.yml`
- Sidecar-only definition: `ops/docker/compose.sidecars.yml`

The full stack compose file wires all seven runtime services plus persistent volumes:

- `db` for control-plane persistence
- `api` for orchestration, approvals, audit, and red-team APIs
- four MCP sidecars for tool execution
- `ui` for the operator console

Every service has a healthcheck, and the API depends on healthy sidecars plus a healthy database before it is considered ready.

## Environment Matrix

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | control-plane database URL | yes |
| `API_KEY` | shared client auth key | yes |
| `DEBUG` | debug mode toggle | no |
| `LOG_LEVEL` | structlog verbosity | no |
| `OPENROUTER_API_KEY` | primary live-model provider key | recommended |
| `OPENROUTER_MODEL` | live-model selection | recommended |
| `GITHUB_TOKEN` | read-only GitHub MCP auth | yes for `github` sidecar |
| `MCP_FILE_SEARCH_URL` | file search sidecar URL | yes |
| `MCP_WEB_FETCH_URL` | web fetch sidecar URL | yes |
| `MCP_SQLITE_QUERY_URL` | sqlite query sidecar URL | yes |
| `MCP_GITHUB_URL` | GitHub sidecar URL | yes |
| `ORCHESTRATOR_CHECKPOINT_PATH` | persisted LangGraph checkpoint DB | yes |
| `AGENTFORGE_API_URL` | UI/CLI API base URL | yes for clients |
| `AGENTFORGE_API_KEY` | UI/CLI auth key | yes for clients |
| `REDTEAM_THRESHOLD_PCT` | CI red-team floor | yes |

## Host Setup Sequence

For a non-Docker local run, the current verified order is:

```powershell
copy .env.example .env
uv sync --directory apps/api
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api python -m agentforge.tools.generate_corpus
uv run --directory apps/api agentforge seed-synthetic --output fixtures/synthetic.sqlite
uv run --directory apps/api agentforge ingest-corpus
uv run --directory apps/api pytest -v
```

## Scale-Out Notes

- The control plane is stateless apart from its database and checkpoint store, so it can scale horizontally once auth, shared storage, and observability are productionized.
- MCP sidecars can scale independently if tool volume grows unevenly.
- PostgreSQL should be the only source of truth in production; SQLite is for development and tests only.
- Long-lived checkpoint and audit storage should be backed up independently from app containers.

## Production Hardening Checklist

- Put secrets in a real secret manager, not plain `.env` files
- Replace shared API-key auth with user-aware auth and authorization
- Terminate TLS ahead of the API and UI
- Put PostgreSQL on managed storage with backups and restore drills
- Rotate `GITHUB_TOKEN` and model-provider keys regularly
- Add centralized logs, metrics, and alerting
- Protect release branches and require CI plus red-team gates before deployment
- Periodically re-run the red-team workflow against the active production model configuration

## Current Local Waiver

Docker compose definitions are included and intended for the release path, but Docker verification is explicitly waived on the maintainer's current Windows host because Docker Desktop and Bitdefender are interfering with container startup there. Host-side verification was used instead for the final release pass.
