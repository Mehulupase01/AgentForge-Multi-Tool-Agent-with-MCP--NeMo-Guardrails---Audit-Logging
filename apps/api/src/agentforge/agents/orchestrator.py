from __future__ import annotations

import json
from typing import Any

from agentforge.agents.base import AGENT_CAPABILITIES, AgentCapability, HandoffMessage
from agentforge.models.agent_run import AgentRole
from agentforge.services.llm_provider import LLMProvider


class OrchestratorAgent:
    capability: AgentCapability = AGENT_CAPABILITIES[AgentRole.ORCHESTRATOR]

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm_provider = llm_provider

    async def route(self, user_prompt: str) -> list[HandoffMessage]:
        if hasattr(self._llm_provider, "generate_supervisor_plan"):
            response = await self._llm_provider.generate_supervisor_plan(user_prompt)
            payload = json.loads(response.text)
            handoffs = payload.get("handoffs", [])
            return [HandoffMessage(to=item["to"], reason=item["reason"], payload=item.get("payload", {})) for item in handoffs]
        return []

    async def compose(self, user_prompt: str, specialist_results: list[dict[str, Any]]) -> str:
        if hasattr(self._llm_provider, "compose_multi_agent_summary"):
            return await self._llm_provider.compose_multi_agent_summary(user_prompt, specialist_results)
        summaries = [item.get("summary", "") for item in specialist_results if item.get("summary")]
        return " ".join(summaries) if summaries else "Task completed without specialist output."
