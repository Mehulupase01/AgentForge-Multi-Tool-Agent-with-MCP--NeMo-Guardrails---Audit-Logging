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
        skills=(),
        policy_summary="Restricted to sqlite_query tools only.",
    ),
    AgentRole.RESEARCHER: AgentCapability(
        role=AgentRole.RESEARCHER,
        description="Finds supporting evidence from the markdown corpus and controlled web fetch tools.",
        tool_scope=("file_search.search_corpus", "file_search.read_document", "web_fetch.fetch_url", "web_fetch.hacker_news_top", "web_fetch.weather_for"),
        skills=(),
        policy_summary="Restricted to file_search and web_fetch tool scopes.",
    ),
    AgentRole.ENGINEER: AgentCapability(
        role=AgentRole.ENGINEER,
        description="Investigates repositories, issues, and GitHub metadata through the github MCP server.",
        tool_scope=("github.list_user_repos", "github.search_issues", "github.get_repo"),
        skills=(),
        policy_summary="Restricted to read-only github MCP tools.",
    ),
    AgentRole.SECRETARY: AgentCapability(
        role=AgentRole.SECRETARY,
        description="Turns provided context into operator-friendly summaries and outward-facing drafts.",
        tool_scope=(),
        skills=(),
        policy_summary="No tools; can only summarize supplied context.",
    ),
    AgentRole.SECURITY_OFFICER: AgentCapability(
        role=AgentRole.SECURITY_OFFICER,
        description="Placeholder in Phase 11; review functionality is fully wired in Phase 15.",
        tool_scope=(),
        skills=(),
        policy_summary="No tools; Phase 11 placeholder approves everything.",
    ),
}
