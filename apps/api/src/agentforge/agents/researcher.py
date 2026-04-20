from __future__ import annotations

from agentforge.agents.base import AgentResult
from agentforge.agents.specialists import SpecialistAgent
from agentforge.models.agent_run import AgentRole


class ResearcherAgent(SpecialistAgent):
    def __init__(self) -> None:
        super().__init__(AgentRole.RESEARCHER)

    async def run(self, **kwargs) -> AgentResult:
        return AgentResult(summary="", data={})
