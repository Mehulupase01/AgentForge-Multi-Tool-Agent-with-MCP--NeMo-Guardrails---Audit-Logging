from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from agentforge.agents.base import AGENT_CAPABILITIES
from agentforge.models.agent_run import AgentRole
from agentforge.schemas.agent import AgentCapabilitiesResponse, AgentRosterItem, AgentRosterResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=AgentRosterResponse)
async def list_agents() -> AgentRosterResponse:
    return AgentRosterResponse(
        data=[
            AgentRosterItem(
                role=capability.role,
                description=capability.description,
                tool_scope=list(capability.tool_scope),
                skills=list(capability.skills),
            )
            for capability in AGENT_CAPABILITIES.values()
        ]
    )


@router.get("/{role}/capabilities", response_model=AgentCapabilitiesResponse)
async def get_agent_capabilities(role: AgentRole) -> AgentCapabilitiesResponse:
    capability = AGENT_CAPABILITIES.get(role)
    if capability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Agent role not found",
                "detail": {"role": role.value},
            },
        )
    return AgentCapabilitiesResponse(
        role=capability.role,
        tools=list(capability.tool_scope),
        skills=list(capability.skills),
        policy_summary=capability.policy_summary,
    )
