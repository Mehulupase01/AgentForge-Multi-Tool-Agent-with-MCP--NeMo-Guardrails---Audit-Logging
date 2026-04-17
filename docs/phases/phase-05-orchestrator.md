# Phase 05 Orchestrator

## Graph Shape

The orchestrator uses a deterministic LangGraph state machine with a memory checkpointer in this phase.

```text
START
  -> plan_node
  -> next_step_node
  -> execute_step_node
  -> record_step_node
  -> next_step_node | finalize_node
  -> finalize_node
END
```

The internal node names use the `_node` suffix because LangGraph reserves state keys separately from node identifiers, and the blueprint state key `plan` would otherwise collide with the planner node name.

## State Schema

```python
class AgentState(TypedDict, total=False):
    task_id: str
    user_prompt: str
    plan: list[dict[str, Any]] | None
    cursor: int
    last_output: dict[str, Any] | None
    final_response: str | None
    error: str | None
    current_step: dict[str, Any] | None
    current_result: dict[str, Any] | None
```

All state values are JSON-safe so the LangGraph checkpointer can serialize them. This matters for `current_result` during `llm_reasoning`: only plain dicts, lists, strings, numbers, booleans, and null values are carried through the graph.

## Planner JSON Schema

The planner returns JSON matching this shape:

```json
{
  "steps": [
    {
      "step_id": "step-1",
      "type": "tool_call",
      "description": "Search the corpus for transformer articles.",
      "server": "file_search",
      "tool": "search_corpus",
      "args": {
        "query": "transformer",
        "limit": 3
      }
    },
    {
      "step_id": "step-2",
      "type": "llm_reasoning",
      "description": "Summarize the collected findings.",
      "args": {}
    }
  ]
}
```

Allowed step types in Phase 5:

- `tool_call`
- `llm_reasoning`
- `approval_gate`

`approval_gate` is accepted in plans but intentionally recorded as a skipped placeholder until Phase 7 wires in the approval queue and checkpoint resume path.

## Persistence Rules

- The planner writes `Task.plan`, marks the task `executing`, records an `LLMCall`, and emits `task.planned`.
- Each executed step writes one `TaskStep`.
- `tool_call` steps also write a `ToolCall`.
- `llm_reasoning` steps also write an `LLMCall`.
- Tool failures mark the task `failed`, persist `Task.error`, emit `task.failed`, and end the graph.
- Successful completion writes `Task.final_response`, marks the task `completed`, and emits `task.completed`.

## SSE Event Pattern

The task stream endpoint replays any retained history first, then switches to the live queue.

Expected Phase 5 event flow:

- `plan`
- `step`
- `step`
- `step`
- `task_completed`

On failures, the terminal event becomes `task_failed`.

## Mock-LLM Test Pattern

The test suite replaces the real provider with a deterministic mock that always returns:

1. `file_search.search_corpus`
2. `web_fetch.hacker_news_top`
3. `llm_reasoning`

That keeps the orchestrator tests stable while still exercising:

- plan parsing
- tool dispatch through the MCP pool abstraction
- step persistence
- LLM call persistence
- SSE ordering
- failure propagation

## Local Verification Notes

- The rebuilt repo `.venv` needed targeted installation of `langgraph`, `langchain-core`, `langchain-openai`, and `openai` before the Phase 5 tests could run on this Windows host.
- The local host environment had `DEBUG=release`, so settings parsing was hardened to treat `release` and `production` as `False` instead of crashing at import time.
- The real-model smoke remains blocked until a local `OPENROUTER_API_KEY` is configured.
- The default OpenRouter model is `openrouter/free` so OpenRouter can pick a current free backend that supports the request's needed features, especially structured JSON planning and later tool-oriented flows.
