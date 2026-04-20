from __future__ import annotations

from agentforge.agents.base import AgentResult
from agentforge.agents.specialists import SpecialistAgent
from agentforge.models.agent_run import AgentRole


class SecurityOfficerAgent(SpecialistAgent):
    def __init__(self) -> None:
        super().__init__(AgentRole.SECURITY_OFFICER)

    async def run(self, **kwargs) -> AgentResult:
        return AgentResult(summary="Security officer placeholder approved the requested work.", data={"verdict": "approved"})
