from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict
from uuid import UUID

from agentforge.models.agent_run import AgentRole


class HandoffMessage(TypedDict):
    to: str
    reason: str
    payload: dict[str, Any]


class AgentResult(TypedDict, total=False):
    summary: str
    data: dict[str, Any]
    next_handoff: HandoffMessage | None


@dataclass(frozen=True, slots=True)
class AgentCapability:
    role: AgentRole
    description: str
    tool_scope: tuple[str, ...]
    skills: tuple[str, ...]
    policy_summary: str


class AgentNode(Protocol):
    capability: AgentCapability

    async def run(
        self,
        *,
        task_id: UUID,
        user_prompt: str,
        handoff: HandoffMessage,
        parent_run_id: UUID | None,
    ) -> AgentResult: ...


AGENT_CAPABILITIES: dict[AgentRole, AgentCapability] = {
    AgentRole.ORCHESTRATOR: AgentCapability(
        role=AgentRole.ORCHESTRATOR,
        description="Routes work across specialist agents and composes the final answer.",
        tool_scope=(),
        skills=(),
        policy_summary="No direct tool access; may only route, compose, and publish handoffs.",
    ),
    AgentRole.ANALYST: AgentCapability(
        role=AgentRole.ANALYST,
        description="Answers workforce, project, and analytics questions from the synthetic SQLite database.",
        tool_scope=("sqlite_query.list_employees", "sqlite_query.list_projects", "sqlite_query.run_select"),
        skills=("workforce_analytics",),
        policy_summary="Restricted to the workforce_analytics skill and sqlite_query tool scope.",
    ),
    AgentRole.RESEARCHER: AgentCapability(
        role=AgentRole.RESEARCHER,
        description="Finds supporting evidence from the markdown corpus and controlled web fetch tools.",
        tool_scope=("file_search.search_corpus", "file_search.read_document", "web_fetch.fetch_url", "web_fetch.hacker_news_top", "web_fetch.weather_for"),
        skills=("corporate_research",),
        policy_summary="Restricted to the corporate_research skill and file_search/web_fetch tool scopes.",
    ),
    AgentRole.ENGINEER: AgentCapability(
        role=AgentRole.ENGINEER,
        description="Investigates repositories, issues, and GitHub metadata through the github MCP server.",
        tool_scope=("github.list_user_repos", "github.search_issues", "github.get_repo"),
        skills=("repo_health",),
        policy_summary="Restricted to the repo_health skill and read-only github MCP tools.",
    ),
    AgentRole.SECRETARY: AgentCapability(
        role=AgentRole.SECRETARY,
        description="Turns provided context into operator-friendly summaries and outward-facing drafts.",
        tool_scope=(),
        skills=("customer_support",),
        policy_summary="No tools; can only draft within the customer_support skill's communication policy.",
    ),
    AgentRole.SECURITY_OFFICER: AgentCapability(
        role=AgentRole.SECURITY_OFFICER,
        description="Performs contextual peer review on plans, risky tool calls, and sensitive long-form outputs.",
        tool_scope=(),
        skills=(),
        policy_summary="No tools; may only review, approve, reject, or flag targets with rationale.",
    ),
}
