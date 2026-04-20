from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from agentforge.config import settings


PLANNER_SYSTEM_PROMPT = """You are the planner for AgentForge.
Return only valid JSON with this schema:
{"steps":[
  {"step_id":"step-1","type":"tool_call","description":"...","server":"file_search","tool":"search_corpus","args":{"query":"...","limit":3}},
  {"step_id":"step-2","type":"llm_reasoning","description":"...","args":{}}
]}
Rules:
- Use only these tool servers when needed: file_search, web_fetch, sqlite_query, github.
- Valid tools by server:
  - file_search.search_corpus(query, limit)
  - file_search.read_document(filename)
  - web_fetch.fetch_url(url, max_bytes)
  - web_fetch.hacker_news_top(count)
  - web_fetch.weather_for(latitude, longitude)
  - sqlite_query.list_employees(department, limit)
  - sqlite_query.list_projects(status, limit)
  - sqlite_query.run_select(sql)
  - github.list_user_repos(username, limit)
  - github.search_issues(repo, query, state, limit)
  - github.get_repo(owner, name)
- Use only type values tool_call, llm_reasoning, approval_gate.
- Keep plans concise and deterministic.
- Do not include markdown fences or commentary.
"""

REASONING_SYSTEM_PROMPT = """You are AgentForge's execution model.
Use the provided task context and prior tool outputs to complete the current step.
Only describe or summarize the data that already exists in the provided context.
Never say that you are about to call a tool, search, browse, or fetch anything.
If the prior tool output is empty, clearly say no relevant results were found.
If the prior tool output includes filenames, titles, snippets, or rows, summarize those concrete results.
Return plain text only.
"""

SUPERVISOR_SYSTEM_PROMPT = """You are AgentForge's multi-agent supervisor.
Return only valid JSON matching:
{
  "handoffs": [
    {
      "to": "analyst|researcher|engineer|secretary|security_officer",
      "reason": "short explanation",
      "payload": {"query": "...", "limit": 3}
    }
  ]
}
Rules:
- Route only when the task clearly benefits from more than one specialist domain.
- analyst handles sqlite_query-style workforce/project data.
- researcher handles corpus/web research.
- engineer handles GitHub questions.
- secretary has no tools and only writes summaries from provided context.
- security_officer is a placeholder in Phase 11; only use it if the task explicitly asks for policy review.
- Keep payloads compact and deterministic.
- Return no markdown fences or commentary.
"""

COMPOSE_MULTI_AGENT_PROMPT = """You are AgentForge's orchestrator summarizer.
Write a concise final answer using only the specialist results provided in the context.
Do not mention internal routing, handoffs, or hidden system behavior.
Return plain text only.
"""


@dataclass(slots=True)
class LLMResponse:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


PLAN_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "agentforge_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["tool_call", "llm_reasoning", "approval_gate"],
                            },
                            "description": {"type": "string"},
                            "server": {"type": ["string", "null"]},
                            "tool": {"type": ["string", "null"]},
                            "args": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["step_id", "type", "description", "args", "server", "tool"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
}

SUPERVISOR_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "agentforge_supervisor_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "handoffs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "enum": ["analyst", "researcher", "engineer", "secretary", "security_officer"],
                            },
                            "reason": {"type": "string"},
                            "payload": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["to", "reason", "payload"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["handoffs"],
            "additionalProperties": False,
        },
    },
}


class LLMProvider:
    def __init__(self) -> None:
        self.provider_name: str
        self.model_name: str
        if settings.openrouter_api_key:
            self.provider_name = "openrouter"
            self.model_name = settings.openrouter_model
            self._client = AsyncOpenAI(
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )
        elif settings.openai_api_key:
            self.provider_name = "openai"
            self.model_name = settings.openai_model
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            self.provider_name = "unconfigured"
            self.model_name = settings.openai_model
            self._client = None

    async def generate_plan(self, user_prompt: str) -> LLMResponse:
        provider_options: dict[str, Any] | None = None
        plugins: list[dict[str, str]] | None = None
        if self.provider_name == "openrouter":
            provider_options = {"require_parameters": True}
            plugins = [{"id": "response-healing"}]
        return await self._chat(
            PLANNER_SYSTEM_PROMPT,
            user_prompt,
            response_format=PLAN_RESPONSE_FORMAT,
            provider_options=provider_options,
            plugins=plugins,
        )

    async def generate_supervisor_plan(self, user_prompt: str) -> LLMResponse:
        provider_options: dict[str, Any] | None = None
        plugins: list[dict[str, str]] | None = None
        if self.provider_name == "openrouter":
            provider_options = {"require_parameters": True}
            plugins = [{"id": "response-healing"}]
        return await self._chat(
            SUPERVISOR_SYSTEM_PROMPT,
            user_prompt,
            response_format=SUPERVISOR_RESPONSE_FORMAT,
            provider_options=provider_options,
            plugins=plugins,
        )

    async def reason_step(self, user_prompt: str) -> LLMResponse:
        return await self._chat(REASONING_SYSTEM_PROMPT, user_prompt)

    async def compose_multi_agent_summary(self, user_prompt: str, specialist_results: list[dict[str, Any]]) -> str:
        payload = {
            "user_prompt": user_prompt,
            "specialist_results": specialist_results,
        }
        response = await self._chat(COMPOSE_MULTI_AGENT_PROMPT, json.dumps(payload, ensure_ascii=True))
        return response.text

    async def _chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
        plugins: list[dict[str, str]] | None = None,
    ) -> LLMResponse:
        if self._client is None:
            raise RuntimeError("No LLM provider configured. Set OPENAI_API_KEY or OPENROUTER_API_KEY.")

        started = time.perf_counter()
        request_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format is not None:
            request_kwargs["response_format"] = response_format
        extra_body: dict[str, Any] = {}
        if provider_options is not None:
            extra_body["provider"] = provider_options
        if plugins is not None:
            extra_body["plugins"] = plugins
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        response = await self._client.chat.completions.create(
            **request_kwargs,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            latency_ms=latency_ms,
        )


_llm_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProvider()
    return _llm_provider
