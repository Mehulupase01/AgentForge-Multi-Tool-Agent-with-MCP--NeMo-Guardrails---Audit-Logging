# Changelog

## 0.2.0 - 2026-04-21

- Added a supervisor-driven multi-agent runtime with six roles: orchestrator, analyst, researcher, engineer, secretary, and security officer.
- Added deterministic self-healing, replay-safe task recovery, YAML skills, security-officer peer review, and proactive trigger ingestion through the new `trigger_worker` sidecar.
- Added AgentOps observability with persisted cost tracking, confidence scoring, low-confidence approval gating, and a Streamlit dashboard for handoffs, confidence, and spend.
- Added a separate v2 release track with migration guidance, AAIF agent manifesting, v2 red-team scenarios, and CI workflows that exercise both v1 and v2 safety gates.
- Standardized the v2 branch around OpenRouter-first execution, including zero-cost tracking for `openrouter/free` in the pricing fixture.

## 0.1.0 - 2026-04-17

- Delivered the FastAPI control plane, four MCP sidecars, LangGraph orchestrator, deterministic guardrails, approvals, red-team suite, Streamlit UI, and standalone CLI.
- Added append-only audit logging with SHA-256 hash-chain integrity verification.
- Added persisted human-in-the-loop approvals with resumable LangGraph execution.
- Added a 50-scenario adversarial red-team suite with JUnit reporting and CI workflow wiring.
- Added full-stack Compose definitions, release docs, AGENTS.md, contribution guide, and verified quickstart guidance.
