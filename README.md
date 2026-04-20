# AgentForge

### Multi-Tool Agent Platform with MCP, NeMo Guardrails, Human Approval, and Tamper-Evident Audit Logging

[![CI](https://github.com/Mehulupase01/AgentForge-Multi-Tool-Agent-with-MCP--NeMo-Guardrails---Audit-Logging/actions/workflows/ci.yml/badge.svg)](https://github.com/Mehulupase01/AgentForge-Multi-Tool-Agent-with-MCP--NeMo-Guardrails---Audit-Logging/actions/workflows/ci.yml)
[![Red-Team](https://github.com/Mehulupase01/AgentForge-Multi-Tool-Agent-with-MCP--NeMo-Guardrails---Audit-Logging/actions/workflows/redteam.yml/badge.svg)](https://github.com/Mehulupase01/AgentForge-Multi-Tool-Agent-with-MCP--NeMo-Guardrails---Audit-Logging/actions/workflows/redteam.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.5-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2.61-1C3C3C)
![MCP](https://img.shields.io/badge/MCP-1.27.0-111111)
![NeMo Guardrails](https://img.shields.io/badge/NeMo_Guardrails-0.11.0-76B900)
![Streamlit](https://img.shields.io/badge/Streamlit-1.41.1-FF4B4B?logo=streamlit&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

AgentForge is a production-structured agent platform where an LLM can plan work, call tools through MCP sidecars, pause risky actions for human approval, and leave behind a tamper-evident audit trail that can be verified after the fact.

This is not a toy chatbot repo. It is a full control plane for enterprise-style agent execution with:

- a FastAPI API for sessions, tasks, approvals, corpus operations, MCP introspection, audit verification, and red-team runs
- a LangGraph orchestrator with persisted checkpoints and resumable execution
- deterministic NeMo Guardrails plus PII redaction and tool allowlisting
- four MCP tool servers for file search, web fetch, SQLite querying, and GitHub access
- a Streamlit operator UI and a standalone CLI
- red-team persistence and CI-backed safety gating

---

## Table of Contents

- [Short Abstract](#short-abstract)
- [Deep Introduction](#deep-introduction)
- [What Makes This Different](#what-makes-this-different)
- [System Architecture](#system-architecture)
- [Request Lifecycle](#request-lifecycle)
- [Safety and Control Model](#safety-and-control-model)
- [MCP Tool Plane](#mcp-tool-plane)
- [Persisted Data Model](#persisted-data-model)
- [Public Interfaces](#public-interfaces)
- [Operator Surfaces](#operator-surfaces)
- [Evaluation and Verification](#evaluation-and-verification)
- [Detailed Local Run Guide](#detailed-local-run-guide)
- [Repository Layout](#repository-layout)
- [Deployment Notes](#deployment-notes)
- [Known Local Waivers](#known-local-waivers)
- [References](#references)

---

## Short Abstract

Most agent demos can answer a prompt. Far fewer can answer operational questions like:

- What tool did the agent call?
- Why was that tool allowed?
- What exactly got blocked by safety policy?
- Could a human intervene before the action executed?
- Can we prove the audit trail was not tampered with?

AgentForge is built around those questions.

The platform accepts a user prompt through a FastAPI control plane, evaluates it with deterministic guardrails, plans execution with an LLM, routes tool calls through dedicated MCP sidecars, pauses risky actions for approval, and records key events into an append-only SHA-256 integrity chain. Operators can monitor and drive the system through HTTP APIs, a Streamlit UI, or a CLI. A persisted red-team runner continuously probes the safety layer and can act as a release gate in CI.

---

## Deep Introduction

The easiest way to understand this repository is to think of it as an agent runtime that has been split into explicit, inspectable subsystems instead of hidden inside one giant prompt loop.

In a lightweight demo, the model receives a prompt, decides what to do, maybe calls a tool, and returns an answer. That is often fine for exploration, but it becomes difficult to operate safely the moment the agent can reach real systems. You need to know which tools exist, what inputs they saw, whether risky actions were blocked, whether the agent paused for approval, and whether the logs can be trusted after an incident.

AgentForge treats those concerns as first-class product requirements.

At runtime, the system creates a session, accepts a task, and runs deterministic input checks before orchestration begins. The orchestrator then asks the configured LLM to generate a plan. Each plan step is persisted. If a step is a tool call, the request is validated against a deny-by-default tool allowlist. Medium-risk and high-risk actions can trigger approval interrupts. Execution state is checkpointed so the task can resume after a human decision. Every major event is written into an append-only audit chain where each event hash depends on the previous event, making integrity verification possible later.

The result is a system that is useful both for building agents and for governing them.

This repository also deliberately separates local workstation constraints from release quality. The maintainer's Windows machine had Docker Desktop and Bitdefender interference during development, so the Docker verification path was explicitly waived locally. Host-side verification, GitHub Actions CI, and the persisted red-team workflow were used instead to bring the repository to a clean release state.

---

## What Makes This Different

### 1. It is an agent control plane, not just a prompt wrapper

The API exposes 25 route handlers across health, sessions, tasks, approvals, audit, corpus, MCP introspection, and red-team operations. The system persists sessions, tasks, steps, tool calls, LLM calls, approval decisions, audit events, corpus documents, and red-team results.

### 2. Tooling is isolated behind MCP sidecars

Instead of wiring tool logic directly into the main API process, AgentForge pushes tools into four dedicated MCP servers:

- `file_search`
- `web_fetch`
- `sqlite_query`
- `github`

That makes the tool surface explicit and introspectable and keeps the control plane cleaner.

### 3. Guardrails are deterministic and auditable

The safety layer is not just “hope the model behaves.” It combines prompt-injection screening, PII redaction, tool allowlisting, risk classification, approval gates, and audit events so blocked behavior is visible and testable.

### 4. Approval is built into the execution graph

Approval is not bolted on afterward. The LangGraph runtime persists state and can interrupt execution, wait for a reviewer decision, and resume the same task deterministically from a checkpoint.

### 5. Red-teaming is part of the product

The repository includes a persisted red-team runner, 50 adversarial scenarios, JUnit reporting, and a GitHub Actions workflow that can enforce a safety threshold.

### 6. Operator UX is included

This repo ships both a Streamlit operator UI and a CLI. It is designed to be used, not only imported.

---

## System Architecture

```mermaid
flowchart LR
    User[User / Operator]
    UI[Streamlit UI]
    CLI[CLI]
    API[FastAPI Control Plane]
    Auth[API Key Auth]
    Guardrails[Guardrails Runner]
    Orchestrator[LangGraph Orchestrator]
    Approvals[Approval Service]
    Audit[Audit Service]
    EventBus[Task Event Bus]
    MCPPool[MCP Client Pool]
    FS[file_search MCP]
    WF[web_fetch MCP]
    SQ[sqlite_query MCP]
    GH[github MCP]
    DB[(PostgreSQL or SQLite)]
    Checkpoints[(Checkpoint SQLite)]
    Corpus[(Corpus Documents)]
    Redteam[Red-Team Runner]

    User --> UI
    User --> CLI
    UI --> API
    CLI --> API
    API --> Auth
    API --> Guardrails
    API --> Orchestrator
    API --> Approvals
    API --> Audit
    API --> EventBus
    API --> MCPPool
    API --> DB
    Orchestrator --> Checkpoints
    Orchestrator --> MCPPool
    MCPPool --> FS
    MCPPool --> WF
    MCPPool --> SQ
    MCPPool --> GH
    API --> Corpus
    Redteam --> API
```

### Major runtime pieces

| Component | Role |
| --- | --- |
| `apps/api` | Main control plane. Hosts the HTTP API, orchestrator wiring, guardrails integration, approvals, audit, corpus operations, and red-team services. |
| `apps/mcp_servers/file_search` | Search and document-read tools over the local markdown corpus. |
| `apps/mcp_servers/web_fetch` | Controlled web retrieval tool surface. |
| `apps/mcp_servers/sqlite_query` | Read-only query server for the synthetic SQLite fixture database. |
| `apps/mcp_servers/github` | Read-only GitHub tool server backed by a scoped token. |
| `apps/ui` | Streamlit-based operator interface. |
| `apps/cli` | Command-line operator client. |

---

## Request Lifecycle

```mermaid
flowchart TD
    A[Create Session] --> B[Submit Task]
    B --> C[Input Guardrails]
    C -->|blocked| D[Reject + Audit]
    C -->|allowed| E[LLM Plan Generation]
    E --> F[Persist Plan + Steps]
    F --> G[Execute Step]
    G -->|tool call| H[Tool Allowlist + Risk Check]
    H -->|blocked| I[Skip/Reject + Audit]
    H -->|approval required| J[Pause for Approval]
    J --> K[Resume from Checkpoint]
    H -->|allowed| L[MCP Tool Execution]
    L --> M[Persist Tool/LLM Call]
    M --> N[Publish SSE Event]
    N --> O{More Steps?}
    O -->|yes| G
    O -->|no| P[Final Response]
    P --> Q[Output Redaction]
    Q --> R[Complete Task + Audit]
```

### What happens in practice

1. A client creates a session.
2. A user prompt is submitted as a task.
3. Input guardrails evaluate the request before orchestration.
4. The LLM generates a structured plan.
5. Each step is executed in sequence.
6. Tool calls are validated against the allowlist and risk rules.
7. If approval is required, the graph interrupts and waits.
8. Execution resumes after approval using a persisted checkpoint.
9. Final output is redacted if needed.
10. The task is completed and the audit chain is extended.

---

## Safety and Control Model

AgentForge’s safety model is layered rather than singular.

### Input safety

- prompt-injection screening
- disallowed request detection
- deterministic rejection path with audit records

### Tool safety

- deny-by-default allowlist
- server and tool pair validation
- risk classification before execution
- approval gate for risky actions

### Output safety

- Presidio-based PII redaction
- structured entity replacements
- output returned only after redaction pass

### Human control

- `awaiting_approval` task state
- persisted approval records
- resumable execution through LangGraph checkpoints

### Audit integrity

- append-only event model
- SHA-256 hash chain
- integrity verification endpoint
- tamper detection tested in the suite

---

## MCP Tool Plane

The MCP layer is one of the core architectural decisions in this project.

### Why MCP is used here

MCP makes the tool surface explicit. The API can ask:

- which tool servers are reachable?
- which tools does each server expose?
- are all sidecars healthy?

This becomes part of readiness and operations instead of hidden application code.

### Included MCP servers

| MCP Server | Purpose | Typical Use |
| --- | --- | --- |
| `file_search` | Searches and reads the local markdown corpus | Find documents about a concept, then retrieve exact passages |
| `web_fetch` | Fetches web content through a controlled interface | Pull external reference content when allowed |
| `sqlite_query` | Runs read-only SQL against the synthetic fixture database | Structured retrieval over tabular data |
| `github` | Uses a scoped token for GitHub lookups | Read repository metadata or inspect GitHub context |

### API introspection endpoints

- `GET /api/v1/mcp/servers`
- `GET /api/v1/mcp/servers/{server_name}/tools`

---

## Persisted Data Model

The repository defines 10 main persisted model modules in the API service.

| Model | Purpose |
| --- | --- |
| `Session` | Top-level conversation/execution container |
| `Task` | Individual user request lifecycle |
| `TaskStep` | Persisted step-by-step execution trail |
| `ToolCall` | Recorded tool call inputs and outputs |
| `LLMCall` | Recorded model invocations and token usage metadata |
| `Approval` | Human decision records for risky actions |
| `AuditEvent` | Append-only audit chain event |
| `CorpusDocument` | Ingested markdown corpus metadata |
| `RedteamRun` | A persisted red-team execution |
| `RedteamResult` | Per-scenario outcome and diagnostics |

This model split is what makes the platform explainable after execution. You can inspect what happened without reverse-engineering a prompt transcript.

---

## Public Interfaces

### Health and readiness

- `GET /api/v1/health/liveness`
- `GET /api/v1/health/readiness`

### Session APIs

- `POST /api/v1/sessions`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `POST /api/v1/sessions/{session_id}/end`

### Task APIs

- `POST /api/v1/sessions/{session_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/steps`
- `GET /api/v1/tasks/{task_id}/stream`
- `POST /api/v1/tasks/{task_id}/resume`

### Approval APIs

- `GET /api/v1/approvals`
- `GET /api/v1/approvals/{approval_id}`
- `POST /api/v1/approvals/{approval_id}/decision`

### Audit APIs

- `GET /api/v1/audit/events`
- `GET /api/v1/audit/sessions/{session_id}/events`
- `GET /api/v1/audit/integrity`

### Corpus APIs

- `POST /api/v1/corpus/reindex`
- `GET /api/v1/corpus/documents`

### MCP APIs

- `GET /api/v1/mcp/servers`
- `GET /api/v1/mcp/servers/{server_name}/tools`

### Red-team APIs

- `POST /api/v1/redteam/run`
- `GET /api/v1/redteam/runs`
- `GET /api/v1/redteam/runs/{run_id}`
- `GET /api/v1/redteam/runs/{run_id}/results`

---

## Operator Surfaces

### CLI

The standalone CLI supports the core operator flow:

- `agentforge session new`
- `agentforge task run "<prompt>"`
- `agentforge approval list`
- `agentforge approval approve <approval_id>`
- `agentforge audit verify`

The CLI also includes SSE parsing logic so operators can watch task execution as a stream instead of polling.

### Streamlit UI

The Streamlit app acts as an operator console for:

- session/task creation
- approval review
- audit inspection
- general control-plane visibility

### API-first operation

Everything the UI and CLI do ultimately maps back to the HTTP API, so the system remains automatable for external tools or future frontends.

---

## Evaluation and Verification

This repository has already been brought through a full phase-by-phase implementation and release pass. The current project state includes:

- 25 API route handlers
- 4 MCP sidecar services
- 50 persisted red-team scenarios
- 53 synthetic corpus documents plus a corpus README
- 62 test functions across API, sidecar, and UI import coverage

### Important verified outcomes

- audit chain integrity verification works
- prompt injection and unsafe requests can be blocked before execution
- risky tool calls can pause for approval and resume later
- SSE task streaming works across both UI and CLI parsers
- MCP sidecar metadata and readiness are surfaced through the API
- the GitHub Actions `ci` workflow and scheduled `redteam` workflow are wired as release gates

### CI/CD status

GitHub Actions provides two main automation lanes:

- `ci.yml`
  - lint
  - API tests
  - MCP sidecar tests
  - image build checks
  - delegated redteam workflow call
- `redteam.yml`
  - environment sync
  - spaCy model install
  - optional live OpenRouter-backed redteam gate
  - deterministic pytest safety suite
  - report artifact upload

The redteam workflow is intentionally adaptive:

- if `OPENROUTER_API_KEY` exists in repository secrets, the live `agentforge redteam-run` gate executes
- if it does not exist, the deterministic pytest safety suite still runs so the safety workflow remains usable in public CI

---

## Detailed Local Run Guide

### 1. Create local environment

```powershell
copy .env.example .env
```

Fill in at least:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openrouter/free
GITHUB_TOKEN=your_scoped_token_here
```

### 2. Sync the API environment

```powershell
uv sync --directory apps/api
uv pip install --python .venv\Scripts\python.exe https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

### 3. Initialize the database

```powershell
uv run --directory apps/api alembic upgrade head
```

### 4. Generate and ingest local knowledge fixtures

```powershell
uv run --directory apps/api python -m agentforge.tools.generate_corpus
uv run --directory apps/api agentforge seed-synthetic --output fixtures/synthetic.sqlite
uv run --directory apps/api agentforge ingest-corpus
```

### 5. Run the test suite

```powershell
uv run --directory apps/api pytest tests -q
uv run --directory apps/api pytest tests/safety/test_redteam_suite.py -q
```

### 6. Run the API

```powershell
uv run --directory apps/api uvicorn agentforge.main:app --app-dir src --host 0.0.0.0 --port 8015
```

### 7. Use the CLI

```powershell
uv run --directory apps/cli agentforge session new
uv run --directory apps/cli agentforge task run "Find transformer content and summarize it."
uv run --directory apps/cli agentforge approval list
uv run --directory apps/cli agentforge audit verify
```

### 8. Run the red-team CLI manually

```powershell
uv run --directory apps/api agentforge redteam-run
```

---

## Repository Layout

```text
apps/
  api/
    alembic/
    src/agentforge/
      guardrails/
      models/
      routers/
      schemas/
      services/
      tools/
    tests/
  cli/
    src/agentforge_cli/
  ui/
    src/agentforge_ui/
    tests/
  mcp_servers/
    file_search/
    web_fetch/
    sqlite_query/
    github/
fixtures/
  corpus/
ops/
  docker/
  github/
.github/
  workflows/
docker-compose.yml
pyproject.toml
uv.lock
```

### Workspace layout

The root `uv` workspace includes:

- `agentforge-api`
- `agentforge-cli`
- `agentforge-ui`
- `file-search-mcp`
- `web-fetch-mcp`
- `sqlite-query-mcp`
- `github-mcp`

---

## Deployment Notes

The repo includes a full Compose layout for the intended release path:

- `ops/docker/compose.full.yml`
- `ops/docker/compose.sidecars.yml`
- `docker-compose.yml`

The intended full stack includes:

- API
- database
- all four MCP sidecars
- Streamlit UI

For production hardening, the important next-layer concerns are:

- proper secret management
- stronger auth than shared API keys
- TLS termination
- managed PostgreSQL and backups
- centralized observability and alerting
- protected branches with CI and redteam gating

---

## Known Local Waivers

This repository should be read with one workstation-specific caveat:

- Docker verification was explicitly waived on the maintainer's Windows host because Docker Desktop and Bitdefender were interfering with container execution.

That waiver applied only to local host verification. GitHub Actions CI remained the release truth source for the repository.

---

## References

- [FastAPI](https://fastapi.tiangolo.com/)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)
- [Streamlit](https://streamlit.io/)
- [OpenRouter](https://openrouter.ai/)
- [GitHub Actions](https://docs.github.com/actions)
- [License](LICENSE)
