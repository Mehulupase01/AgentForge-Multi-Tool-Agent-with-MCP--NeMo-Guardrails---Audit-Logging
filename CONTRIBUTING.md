# Contributing

## Workflow

- Work phase-by-phase against the project blueprint and repo memory files.
- Keep changes small, intentional, and verified before pushing.
- Do not commit secrets, local `.env` files, generated SQLite databases, or runtime checkpoint artifacts.
- If you change public behavior, update the docs and verification log in the same pass.

## Local Development Loop

```powershell
uv sync --directory apps/api
uv run --directory apps/api alembic upgrade head
uv run --directory apps/api pytest -v
```

Useful targeted checks:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/mcp_servers/file_search/tests apps/mcp_servers/web_fetch/tests apps/mcp_servers/sqlite_query/tests apps/mcp_servers/github/tests -q
.\.venv\Scripts\python.exe -m pytest apps/api/tests/test_sse_compat.py apps/ui/tests/test_imports.py -v
uvx ruff check apps
```

## Quality Gates

- API changes should include or update pytest coverage.
- MCP changes should keep sidecar tests green.
- UI or CLI changes should keep `apps/api/tests/test_sse_compat.py` and `apps/ui/tests/test_imports.py` green.
- Red-team changes must preserve the `>= 96%` CI floor and `>= 98%` target.
- Release-facing changes should keep the README, deployment guide, AGENTS.md, and changelog aligned with reality.

## Pull Requests

- Summarize user-facing behavior changes first.
- List the verification commands you ran.
- Call out any environment waivers, such as Docker being unavailable on the local host.
- Mention any changed safety behavior explicitly.
