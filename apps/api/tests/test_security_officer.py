from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from agentforge.agents.supervisor_graph import SupervisorGraph
from agentforge.models.approval import Approval, RiskLevel
from agentforge.models.audit_event import AuditEvent
from agentforge.models.review_record import ReviewRecord, ReviewTargetType, ReviewVerdict
from agentforge.models.session import Session, SessionStatus
from agentforge.models.task import Task, TaskStatus
from agentforge.services.approval_service import ApprovalService
from agentforge.services.audit_service import AuditService
from agentforge.services.task_event_bus import TaskEventBus


class MockLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompt_tokens = 8
        self.completion_tokens = 12
        self.latency_ms = 1


class SecurityOfficerTestProvider:
    def __init__(
        self,
        handoffs: list[dict],
        *,
        plan_verdict: str = "approved",
        tool_verdict: str = "approved",
        output_verdict: str = "approved",
        timeout_on_review: bool = False,
        final_response: str = "Completed safely.",
    ) -> None:
        self._handoffs = handoffs
        self._plan_verdict = plan_verdict
        self._tool_verdict = tool_verdict
        self._output_verdict = output_verdict
        self._timeout_on_review = timeout_on_review
        self._final_response = final_response

    async def generate_supervisor_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(json.dumps({"handoffs": self._handoffs}))

    async def compose_multi_agent_summary(self, user_prompt: str, specialist_results: list[dict]) -> str:
        return self._final_response

    async def review_security(self, payload: dict) -> MockLLMResponse:
        if self._timeout_on_review:
            raise asyncio.TimeoutError("security officer timed out")
        target_type = payload["target_type"]
        verdict = {
            "plan": self._plan_verdict,
            "tool_call": self._tool_verdict,
            "llm_output": self._output_verdict,
        }.get(target_type, "approved")
        rationale = {
            "approved": "Security Officer approved the review target.",
            "rejected": "Security Officer rejected the review target.",
            "flagged": "Security Officer flagged the review target.",
        }[verdict]
        return MockLLMResponse(
            json.dumps(
                {
                    "verdict": verdict,
                    "rationale": rationale,
                    "evidence": {"signals": [f"{target_type}:{verdict}"]},
                }
            )
        )


class HeuristicOutputProvider:
    def __init__(self, handoffs: list[dict], final_response: str) -> None:
        self._handoffs = handoffs
        self._final_response = final_response

    async def generate_supervisor_plan(self, user_prompt: str) -> MockLLMResponse:
        return MockLLMResponse(json.dumps({"handoffs": self._handoffs}))

    async def compose_multi_agent_summary(self, user_prompt: str, specialist_results: list[dict]) -> str:
        return self._final_response


class FakeSecurityMCPPool:
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        if (server_name, tool_name) == ("file_search", "search_corpus"):
            return [{"filename": "01-transformers.md", "title": "Transformers", "score": 9}]
        if (server_name, tool_name) == ("sqlite_query", "list_employees"):
            return [{"employee_id": 1, "name": "Ava", "department": "Engineering"}]
        if (server_name, tool_name) == ("sqlite_query", "run_select"):
            return [{"name": "Ava", "salary_band": "L4"}]
        raise KeyError((server_name, tool_name))


async def create_task_row(session_factory, prompt: str) -> Task:
    async with session_factory() as session:
        work_session = Session(
            user_id="security-officer-test",
            status=SessionStatus.ACTIVE,
            started_at=datetime.now(UTC),
            metadata_json={},
        )
        session.add(work_session)
        await session.flush()
        task = Task(
            session_id=work_session.id,
            user_prompt=prompt,
            status=TaskStatus.PLANNING,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


def build_graph(session_factory, provider) -> tuple[SupervisorGraph, TaskEventBus]:
    event_bus = TaskEventBus()
    graph = SupervisorGraph(
        session_factory=session_factory,
        mcp_pool=FakeSecurityMCPPool(),
        event_bus=event_bus,
        audit_service=AuditService(),
        approval_service=ApprovalService(),
        llm_provider=provider,
    )
    return graph, event_bus


@pytest.mark.asyncio
async def test_so_approves_benign_plan(session_factory, client: AsyncClient) -> None:
    provider = SecurityOfficerTestProvider(
        [
            {"to": "researcher", "reason": "Find AI articles.", "payload": {"query": "AI", "limit": 1}},
            {"to": "analyst", "reason": "List engineers.", "payload": {"department": "Engineering", "limit": 1}},
        ]
    )
    graph, _ = build_graph(session_factory, provider)
    task = await create_task_row(session_factory, "Research AI and list engineers.")

    result = await graph.run(task.id, task.user_prompt)

    assert result.awaiting_approval is False
    assert result.final_response == "Completed safely."

    async with session_factory() as session:
        task_row = await session.get(Task, task.id)
        reviews = list((await session.execute(select(ReviewRecord).where(ReviewRecord.task_id == task.id))).scalars())
        assert task_row is not None
        assert task_row.status == TaskStatus.COMPLETED
        assert len(reviews) == 1
        assert reviews[0].target_type == ReviewTargetType.PLAN
        assert reviews[0].verdict == ReviewVerdict.APPROVED

    reviews_response = await client.get(f"/api/v1/tasks/{task.id}/reviews")
    assert reviews_response.status_code == 200
    payload = reviews_response.json()
    assert payload["meta"]["total"] == 1
    assert payload["data"][0]["verdict"] == "approved"


@pytest.mark.asyncio
async def test_so_rejects_exfiltration_plan(session_factory) -> None:
    provider = SecurityOfficerTestProvider(
        [
            {
                "to": "analyst",
                "reason": "Export all employees with salary band details.",
                "payload": {
                    "sql": "SELECT e.name, s.salary_band FROM employees e JOIN salary_band s ON e.employee_id = s.employee_id LIMIT 20",
                    "description": "List all employees with salary_band filter.",
                },
            }
        ],
        plan_verdict="rejected",
    )
    graph, event_bus = build_graph(session_factory, provider)
    task = await create_task_row(session_factory, "Export all employees with salary band details.")

    result = await graph.run(task.id, task.user_prompt)

    assert result.awaiting_approval is True
    history = await event_bus.get_history(task.id)
    assert any(event["event"] == "review_verdict" for event in history)

    async with session_factory() as session:
        task_row = await session.get(Task, task.id)
        approval = (
            await session.execute(select(Approval).where(Approval.task_id == task.id).order_by(Approval.requested_at.desc()))
        ).scalars().first()
        review = (
            await session.execute(select(ReviewRecord).where(ReviewRecord.task_id == task.id).order_by(ReviewRecord.reviewed_at.desc()))
        ).scalars().first()
        assert task_row is not None
        assert task_row.status == TaskStatus.AWAITING_APPROVAL
        assert approval is not None
        assert approval.risk_level == RiskLevel.HIGH
        assert approval.risk_reason.startswith("security_officer_rejected:")
        assert review is not None
        assert review.target_type == ReviewTargetType.PLAN
        assert review.verdict == ReviewVerdict.REJECTED


@pytest.mark.asyncio
async def test_so_flags_pii_in_output(session_factory) -> None:
    long_output = " ".join(["contact", "mehul@example.com"] * 550)
    provider = HeuristicOutputProvider(
        [{"to": "secretary", "reason": "Write the summary.", "payload": {"draft": "safe"}}],
        final_response=long_output,
    )
    graph, _ = build_graph(session_factory, provider)
    task = await create_task_row(session_factory, "Write a long summary.")

    result = await graph.run(task.id, task.user_prompt)

    assert result.final_response.startswith("[REDACTED:")
    async with session_factory() as session:
        task_row = await session.get(Task, task.id)
        review = (
            await session.execute(
                select(ReviewRecord)
                .where(ReviewRecord.task_id == task.id, ReviewRecord.target_type == ReviewTargetType.LLM_OUTPUT)
                .order_by(ReviewRecord.reviewed_at.desc())
            )
        ).scalars().first()
        flagged_event = (
            await session.execute(select(AuditEvent).where(AuditEvent.task_id == task.id, AuditEvent.event_type == "review.flagged"))
        ).scalars().first()
        assert task_row is not None
        assert task_row.status == TaskStatus.COMPLETED
        assert review is not None
        assert review.verdict == ReviewVerdict.FLAGGED
        assert flagged_event is not None


@pytest.mark.asyncio
async def test_so_required_for_medium_tool(session_factory) -> None:
    provider = SecurityOfficerTestProvider(
        [
            {
                "to": "researcher",
                "reason": "Fetch an external industry report.",
                "payload": {
                    "server": "web_fetch",
                    "tool": "fetch_url",
                    "args": {"url": "https://unknown.example.com/report", "max_bytes": 2048},
                    "description": "Fetch an external industry report.",
                },
            }
        ],
        tool_verdict="rejected",
    )
    graph, _ = build_graph(session_factory, provider)
    task = await create_task_row(session_factory, "Fetch an external industry report.")

    result = await graph.run(task.id, task.user_prompt)

    assert result.awaiting_approval is True
    async with session_factory() as session:
        approval = (
            await session.execute(select(Approval).where(Approval.task_id == task.id).order_by(Approval.requested_at.desc()))
        ).scalars().first()
        review = (
            await session.execute(
                select(ReviewRecord)
                .where(ReviewRecord.task_id == task.id, ReviewRecord.target_type == ReviewTargetType.TOOL_CALL)
                .order_by(ReviewRecord.reviewed_at.desc())
            )
        ).scalars().first()
        assert approval is not None
        assert approval.risk_level == RiskLevel.MEDIUM
        assert approval.risk_reason.startswith("security_officer_rejected:")
        assert review is not None
        assert review.verdict == ReviewVerdict.REJECTED


@pytest.mark.asyncio
async def test_so_timeout_fails_safe(session_factory) -> None:
    provider = SecurityOfficerTestProvider(
        [{"to": "researcher", "reason": "Find one AI article.", "payload": {"query": "AI", "limit": 1}}],
        timeout_on_review=True,
    )
    graph, _ = build_graph(session_factory, provider)
    task = await create_task_row(session_factory, "Find one AI article.")

    result = await graph.run(task.id, task.user_prompt)

    assert result.awaiting_approval is True
    async with session_factory() as session:
        review = (
            await session.execute(select(ReviewRecord).where(ReviewRecord.task_id == task.id).order_by(ReviewRecord.reviewed_at.desc()))
        ).scalars().first()
        assert review is not None
        assert review.verdict == ReviewVerdict.REJECTED
        assert review.rationale == "SO timeout"
