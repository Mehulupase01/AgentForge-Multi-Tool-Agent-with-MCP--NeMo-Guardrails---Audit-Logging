# AGENTS.md

## Identity

- Agent: `AgentForge`
- Version: `0.1.0`
- Purpose: enterprise-safe multi-tool agent platform
- Interfaces: FastAPI control plane, Streamlit UI, standalone CLI

## Capabilities

- Decomposes natural-language requests into explicit multi-step plans
- Executes approved steps through MCP tool servers
- Streams plan, step, and completion events over SSE
- Applies deterministic guardrails for PII, prompt injection, topic restrictions, and tool allowlists
- Pauses medium- and high-risk tool actions for human approval
- Persists tool calls, LLM calls, task steps, and audit events
- Verifies audit integrity through a SHA-256 append-only chain
- Runs a persisted red-team suite and emits JUnit reports for CI

## Inputs

- Operator prompts over HTTP, Streamlit UI, or CLI
- Configuration through environment variables
- Markdown corpus files under `fixtures/corpus/`
- Synthetic SQLite data under `fixtures/synthetic.sqlite`
- Read-only GitHub API access through a scoped token

## Tools

- `file_search`
  Source: repo fixture corpus
  Operations: `search_corpus`, `read_document`
- `web_fetch`
  Source: allowlisted web endpoints
  Operations: `fetch_url`, `hacker_news_top`, `weather_for`
- `sqlite_query`
  Source: synthetic SQLite fixture DB
  Operations: `list_employees`, `list_projects`, `run_select`
- `github`
  Source: GitHub REST API
  Operations: `list_user_repos`, `search_issues`, `get_repo`

## Data Sources

- Control-plane database: PostgreSQL in production, SQLite in development and tests
- Synthetic fixture DB: `fixtures/synthetic.sqlite`
- Corpus: `fixtures/corpus/`
- External services: GitHub, Hacker News, Open-Meteo, allowlisted fetch targets, OpenRouter

## Safety Boundaries

- Input guardrails can reject tasks before any tool or model call is executed
- Output guardrails redact detected PII before final responses are stored or returned
- Tool execution is deny-by-default outside the allowlist
- Risky tool actions move tasks into `awaiting_approval`
- Audit history is append-only in application code and integrity-checkable
- GitHub access is read-only by design

## Known Limitations

- Demo auth is a single shared `X-API-Key`, not user-aware auth
- Live-model behavior depends on OpenRouter availability, quota, and free-model routing
- Docker verification is waived on the maintainer's current Windows host because the local Docker stack is broken
- The public repo intentionally does not include the local-only blueprint artifacts

## Escalation Paths

- High-risk or ambiguous tool requests require explicit approval
- Audit integrity failures should be treated as an incident and block further trust in the environment
- If policy and operator intent disagree, the system should block and escalate to human review

## Operator Checks

- Health: `GET /api/v1/health/liveness`, `GET /api/v1/health/readiness`
- Audit integrity: `GET /api/v1/audit/integrity`
- Approvals queue: `GET /api/v1/approvals`
- Red-team execution: `POST /api/v1/redteam/run`
