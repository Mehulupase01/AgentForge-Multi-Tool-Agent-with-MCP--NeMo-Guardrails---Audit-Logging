# AGENTS.v2.md

## Identity

- Agent system: `AgentForge`
- Branch release: `0.2.0`
- Runtime mode: supervised multi-agent orchestration
- Interfaces: FastAPI control plane, Streamlit UI, standalone CLI, webhook + schedule triggers

## System Contract

AgentForge v2 runs a supervisor graph that routes work between six role-specialized agents. The system keeps the original v1 safety stack, audit chain, approvals, and MCP tool isolation, then layers on self-healing, replay, skills, second-line review, and operator analytics.

## Shared Runtime Boundaries

- All roles operate inside the same guardrail, approval, and audit framework.
- Raw tool access is mediated through skills or explicit orchestration policy.
- MCP tools remain read-oriented by default.
- High-risk work escalates to approvals and, when configured, the Security Officer.
- Replay must never silently duplicate side-effectful work.

## Role Roster

### `orchestrator`

- Capabilities: decomposes user intent, produces supervisor plans, selects specialists, composes final responses
- Tools: indirect access to all allowlisted skills, task state, task events, confidence scoring hooks
- Skills: planning, summarization, routing, final synthesis
- Limits: should not bypass specialist scope or approval policy
- Escalation path: hand off to Security Officer for risky plans, create human approval for unresolved ambiguity

### `analyst`

- Capabilities: structured reasoning, requirement extraction, corpus synthesis, discrepancy spotting
- Tools: corpus-backed research skills, read-only MCP access via skills
- Skills: `corpus_research`, `summarize_findings`
- Limits: no write actions, no direct approval bypass, no unrestricted tool chaining
- Escalation path: hand back to orchestrator when evidence is incomplete or risk grows

### `researcher`

- Capabilities: external retrieval, document comparison, evidence gathering
- Tools: `web_fetch`, `file_search`, GitHub read skills when explicitly allowed
- Skills: `web_research`, `github_issue_lookup`
- Limits: topic scope and rate policy must be respected
- Escalation path: hand off to analyst for synthesis or to Security Officer if evidence is sensitive

### `engineer`

- Capabilities: repository inspection, implementation planning, code-change reasoning, replay-safe action proposals
- Tools: GitHub read skills, repository/corpus skills, SQLite read skills when justified
- Skills: `repo_triage`, `implementation_plan`
- Limits: no implicit write privileges; risky code or release actions require approval/review
- Escalation path: route risky or externally visible changes through Security Officer and human approval

### `secretary`

- Capabilities: operator-facing formatting, note capture, digest creation, low-risk administrative transforms
- Tools: summarization and templating skills only
- Skills: `status_digest`, `meeting_summary`
- Limits: must not originate risky actions, external sends, or privileged tool usage
- Escalation path: hand any action-bearing request back to orchestrator

### `security_officer`

- Capabilities: second-line review of plans, medium/high-risk tool intents, flagged long-form outputs, policy rationale
- Tools: review-only reasoning and policy inspection, no external side-effectful tools
- Skills: `security_review`, `policy_verdict`
- Limits: fail safe on timeout, reject on insufficient evidence, cannot lower base guardrail standards
- Escalation path: reject and create operator-visible rationale or require human approval

## Skills Contract

- Skills are versioned YAML documents loaded at startup and reloadable through `POST /api/v1/skills/reload`.
- Policy schema is intentionally closed to five keys.
- Policy checks can truncate, redact, approval-gate, topic-scope, or rate-limit tool use.
- Skill invocations are persisted and auditable.

## Observability Expectations

- Every role transition should be visible through task SSE as `agent_handoff`.
- Retry activity should be visible as `agent_retry`.
- Review outcomes should be visible as `review_verdict`.
- Cost and confidence updates should surface both in task APIs and the Streamlit AgentOps page.

## Escalation Matrix

| Situation | Expected behavior |
| --- | --- |
| Prompt injection or prohibited request | Block before orchestration and emit guardrail audit events |
| Tool action rated MEDIUM/HIGH risk | Create approval and, when configured, request Security Officer review |
| Specialist failure classified transient | Reflect, retry, and record retry lineage |
| Specialist failure classified persistent | Escalate to orchestrator or approval path |
| Confidence below threshold | Create LOW-risk approval with `confidence_gate` rationale |
| Replay request for stale or non-idempotent work | Refuse or escalate instead of re-running silently |

## Operator Checks

- Agents roster: `GET /api/v1/agents`
- Role capabilities: `GET /api/v1/agents/{role}/capabilities`
- Skills registry: `GET /api/v1/skills`
- Replay: `POST /api/v1/tasks/{id}/replay`
- Reviews: `GET /api/v1/tasks/{id}/reviews`
- Triggers: `GET /api/v1/triggers`
- AgentOps: `/api/v1/observability/*`
