from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agentforge.agents.base import AGENT_CAPABILITIES, AgentCapability, AgentResult, HandoffMessage
from agentforge.models.agent_run import AgentRole


@dataclass(slots=True)
class SpecialistRequest:
    role: AgentRole
    tool_name: str | None
    args: dict[str, Any]
    description: str


class SpecialistPlanner:
    @staticmethod
    def build_request(role: AgentRole, handoff: HandoffMessage) -> SpecialistRequest:
        payload = handoff.get("payload", {})
        explicit_server = payload.get("server")
        explicit_tool = payload.get("tool")
        if explicit_server and explicit_tool:
            return SpecialistRequest(
                role=role,
                tool_name=f"{explicit_server}.{explicit_tool}",
                args=payload.get("args", {}),
                description=payload.get("description", handoff["reason"]),
            )
        if role == AgentRole.RESEARCHER:
            if "url" in payload:
                return SpecialistRequest(
                    role=role,
                    tool_name="fetch_url",
                    args={"url": payload["url"], "max_bytes": payload.get("max_bytes", 4000)},
                    description=payload.get("description", "Fetch source material from the web."),
                )
            return SpecialistRequest(
                role=role,
                tool_name="search_corpus",
                args={"query": payload.get("query", payload.get("topic", "ai")), "limit": payload.get("limit", 3)},
                description=payload.get("description", "Search the corpus for supporting research."),
            )

        if role == AgentRole.ANALYST:
            if "sql" in payload:
                return SpecialistRequest(
                    role=role,
                    tool_name="run_select",
                    args={"sql": payload["sql"]},
                    description=payload.get("description", "Run a bounded analytical SQL query."),
                )
            if "status" in payload:
                return SpecialistRequest(
                    role=role,
                    tool_name="list_projects",
                    args={"status": payload["status"], "limit": payload.get("limit", 3)},
                    description=payload.get("description", "List projects from the synthetic database."),
                )
            return SpecialistRequest(
                role=role,
                tool_name="list_employees",
                args={"department": payload.get("department"), "limit": payload.get("limit", 3)},
                description=payload.get("description", "List relevant employees from the synthetic database."),
            )

        if role == AgentRole.ENGINEER:
            if payload.get("repo"):
                owner, _, name = str(payload["repo"]).partition("/")
                return SpecialistRequest(
                    role=role,
                    tool_name="get_repo",
                    args={"owner": owner, "name": name},
                    description=payload.get("description", "Inspect repository metadata."),
                )
            if payload.get("query") and payload.get("repo"):
                return SpecialistRequest(
                    role=role,
                    tool_name="search_issues",
                    args={"repo": payload["repo"], "query": payload["query"], "state": payload.get("state", "open"), "limit": payload.get("limit", 5)},
                    description=payload.get("description", "Search GitHub issues for the requested topic."),
                )
            return SpecialistRequest(
                role=role,
                tool_name="list_user_repos",
                args={"username": payload.get("username", "openai"), "limit": payload.get("limit", 5)},
                description=payload.get("description", "List repositories for a GitHub user."),
            )

        return SpecialistRequest(role=role, tool_name=None, args=payload, description=handoff["reason"])


class SpecialistSummarizer:
    @staticmethod
    def summarize(role: AgentRole, result: Any) -> str:
        if role == AgentRole.RESEARCHER:
            items = result if isinstance(result, list) else [result]
            if not items:
                return "Researcher found no relevant evidence."
            top = items[0]
            title = top.get("title") or top.get("filename") or "result"
            return f"Researcher found {len(items)} relevant item(s), led by '{title}'."
        if role == AgentRole.ANALYST:
            items = result if isinstance(result, list) else [result]
            return f"Analyst returned {len(items)} structured row(s) from sqlite_query."
        if role == AgentRole.ENGINEER:
            if isinstance(result, dict):
                return f"Engineer inspected repository data for {result.get('full_name', 'the requested repo')}."
            items = result if isinstance(result, list) else [result]
            return f"Engineer returned {len(items)} GitHub result item(s)."
        if role == AgentRole.SECRETARY:
            return str(result)
        return "Security officer placeholder approved the request."


class SpecialistAgent:
    def __init__(self, role: AgentRole) -> None:
        self.capability: AgentCapability = AGENT_CAPABILITIES[role]

    async def run(
        self,
        *,
        task_id: UUID,
        user_prompt: str,
        handoff: HandoffMessage,
        parent_run_id: UUID | None,
    ) -> AgentResult:
        raise NotImplementedError
