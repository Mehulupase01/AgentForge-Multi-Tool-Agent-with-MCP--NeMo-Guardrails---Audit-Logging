# Phase 06 Guardrails

## Scope

Phase 6 wraps task intake, tool dispatch, and LLM output handling with a composable guardrails layer.

Implemented rails:

- Input PII redaction with Presidio-backed detection and placeholder replacement.
- Input prompt-injection detection with deterministic regex and heuristic scans.
- Topic gating for clearly harmful or out-of-scope requests.
- Output PII redaction before model text is persisted or shown back to the operator.
- Execution allowlist checks for MCP tool usage.

## Runtime Flow

1. `POST /api/v1/sessions/{id}/tasks` runs `GuardrailsRunner.process_input(...)`.
2. If the prompt is blocked:
   - a `Task` is persisted as `rejected`
   - a `guardrail_block` `TaskStep` is written
   - audit events are emitted
   - the API returns `400 GUARDRAIL_BLOCKED`
3. If the prompt is allowed:
   - any PII is redacted before the task prompt is stored
   - the planner LLM call records `input_rails_json`
4. During execution:
   - each tool call is checked against the allowlist
   - disallowed tools become skipped `guardrail_block` steps with audit events
   - each LLM reasoning output is run through output redaction and persisted with `output_rails_json`

## PII Behavior

Entities currently targeted:

- `EMAIL_ADDRESS`
- `PHONE_NUMBER`
- `US_SSN`
- `IBAN_CODE`
- `CREDIT_CARD`
- `PERSON`
- `IP_ADDRESS`
- `IN_AADHAAR`
- `EU_PASSPORT`

The implementation uses Presidio for detection, but the replacement itself is intentionally done in-process with deterministic placeholders like `<EMAIL_ADDRESS>` and `<US_SSN>`. That keeps the redaction output stable across tests and future phases.

## Injection Heuristics

Current deterministic prompt-injection triggers include:

- `ignore previous instructions`
- `system:`
- `you are now`
- `/admin`
- long base64-like blobs
- explicit attempts to reveal hidden or system prompts

## Tool Allowlist

The allowlist lives in:

- `apps/api/src/agentforge/guardrails/config/tool_allowlist.yml`

The current Phase 6 allowlist includes the full Phase 4 tool surface. Tests can override it with a temporary file to simulate blocked tools.

## NeMo Assets

The repo now includes:

- `config.yml`
- `rails.co`
- `prompts.yml`

These assets document the intended NeMo Guardrails model and prompt structure and keep the repo aligned with the blueprint’s guardrail configuration shape. The live Phase 6 enforcement path remains deterministic in Python so the verification suite stays stable on the free-model route.

## Local Install Note

The blueprint verification step uses:

```powershell
python -m spacy download en_core_web_sm-3.7.1 --direct
```

On this Windows host, the repo `.venv` does not include `pip`, so the local equivalent used for verification was:

```powershell
uv pip install --python .venv\Scripts\python.exe https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

That produced the same runtime state for Phase 6 verification.
