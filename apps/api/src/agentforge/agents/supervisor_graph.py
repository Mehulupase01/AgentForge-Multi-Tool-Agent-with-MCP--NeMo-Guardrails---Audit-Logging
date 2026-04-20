from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.agents.base import AGENT_CAPABILITIES, HandoffMessage
from agentforge.agents.orchestrator import OrchestratorAgent
from agentforge.agents.specialists import SpecialistPlanner, SpecialistSummarizer
from agentforge.models.agent_run import AgentRole, AgentRun, AgentRunStatus
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.models.tool_call import ToolCall
from agentforge.schemas.task import PlanStep
from agentforge.services.audit_service import AuditService
from agentforge.services.mcp_client_pool import MCPClientPool
from agentforge.services.task_event_bus import TaskEventBus


@dataclass(slots=True)
class SupervisorExecutionResult:
    supervisor_plan: dict[str, Any]
    final_response: str
    rejected: bool = False
    error: str | None = None


class SupervisorGraph:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        mcp_pool: MCPClientPool,
        event_bus: TaskEventBus,
        audit_service: AuditService,
        llm_provider,
    ) -> None:
        self._session_factory = session_factory
        self._mcp_pool = mcp_pool
        self._event_bus = event_bus
        self._audit_service = audit_service
        self._orchestrator = OrchestratorAgent(llm_provider)

    async def run(self, task_id: UUID, user_prompt: str) -> SupervisorExecutionResult:
        handoffs = await self._orchestrator.route(user_prompt)
        if not handoffs:
            return SupervisorExecutionResult(supervisor_plan={"handoffs": [], "steps_expected": 0}, final_response="")

        supervisor_plan = {"handoffs": handoffs, "steps_expected": len(handoffs)}
        specialist_results: list[dict[str, Any]] = []

        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found during supervisor execution")
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.now(UTC)
            session.add(
                AgentRun(
                    task_id=task_id,
                    role=AgentRole.ORCHESTRATOR,
                    started_at=datetime.now(UTC),
                    status=AgentRunStatus.RUNNING,
                    result_json=supervisor_plan,
                )
            )
            await session.commit()

        orchestrator_run_id = await self._latest_run_id(task_id, AgentRole.ORCHESTRATOR)

        for handoff in handoffs:
            role = AgentRole(handoff["to"])
            await self._event_bus.publish(
                task_id,
                "agent_handoff",
                {"from": AgentRole.ORCHESTRATOR.value, "to": role.value, "reason": handoff["reason"]},
            )
            agent_run_id = await self._create_agent_run(task_id, role, orchestrator_run_id, handoff)
            specialist_result = await self._run_specialist(task_id, user_prompt, role, handoff, agent_run_id)
            specialist_results.append(specialist_result)
            await self._finalize_agent_run(agent_run_id, specialist_result)
            if specialist_result.get("rejected"):
                await self._finalize_orchestrator_run(task_id, supervisor_plan, AgentRunStatus.REJECTED)
                return SupervisorExecutionResult(
                    supervisor_plan=supervisor_plan,
                    final_response="",
                    rejected=True,
                    error=str(specialist_result["summary"]),
                )

        final_response = await self._orchestrator.compose(user_prompt, specialist_results)

        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found during supervisor finalization")
            task.status = TaskStatus.COMPLETED
            task.final_response = final_response
            task.completed_at = datetime.now(UTC)
            await session.commit()
            await self._audit_service.record_event(
                session,
                event_type="task.completed",
                actor="system",
                payload={"task_id": str(task_id), "final_response": final_response},
                session_id=task.session_id,
                task_id=task.id,
            )

        await self._event_bus.publish(task_id, "task_completed", {"final_response": final_response})
        await self._finalize_orchestrator_run(task_id, {**supervisor_plan, "final_response": final_response}, AgentRunStatus.COMPLETED)
        return SupervisorExecutionResult(supervisor_plan=supervisor_plan, final_response=final_response)

    async def _run_specialist(
        self,
        task_id: UUID,
        user_prompt: str,
        role: AgentRole,
        handoff: HandoffMessage,
        agent_run_id: UUID,
    ) -> dict[str, Any]:
        request = SpecialistPlanner.build_request(role, handoff)
        if request.tool_name is None:
            summary = SpecialistSummarizer.summarize(role, handoff["payload"])
            return {"role": role.value, "summary": summary, "data": handoff["payload"]}

        server_name = request.tool_name.split(".", 1)[0] if "." in request.tool_name else self._server_for_role(role)
        tool_name = request.tool_name.split(".", 1)[-1]
        allowed_tools = set(AGENT_CAPABILITIES[role].tool_scope)
        qualified_tool = f"{server_name}.{tool_name}"
        if qualified_tool not in allowed_tools:
            await self._record_guardrail_rejection(task_id, role, handoff, qualified_tool, agent_run_id)
            return {
                "role": role.value,
                "summary": f"{role.value} attempted out-of-scope tool {qualified_tool} and was rejected.",
                "data": {"rejected_tool": qualified_tool},
                "rejected": True,
            }

        tool_result = await self._mcp_pool.call_tool(server_name, tool_name, request.args)
        summary = SpecialistSummarizer.summarize(role, tool_result)
        await self._record_tool_step(task_id, role, request.description, server_name, tool_name, request.args, tool_result, agent_run_id)
        return {"role": role.value, "summary": summary, "data": tool_result}

    async def _record_tool_step(
        self,
        task_id: UUID,
        role: AgentRole,
        description: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        agent_run_id: UUID,
    ) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while recording specialist step")
            ordinal = await self._next_ordinal(session, task_id)
            task_step = TaskStep(
                task_id=task_id,
                ordinal=ordinal,
                step_type=StepType.TOOL_CALL,
                description=description,
                status=StepStatus.COMPLETED,
                agent_role=role,
                attempt=1,
                agent_run_id=agent_run_id,
                input_json={"server": server_name, "tool": tool_name, "args": arguments},
                output_json=result,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            session.add(task_step)
            await session.flush()
            session.add(
                ToolCall(
                    task_step_id=task_step.id,
                    server_name=server_name,
                    tool_name=tool_name,
                    arguments_json=arguments,
                    result_json=result,
                    error=None,
                    duration_ms=0,
                    required_approval=False,
                    started_at=task_step.started_at,
                    completed_at=task_step.completed_at,
                )
            )
            await session.commit()
            await self._audit_service.record_event(
                session,
                event_type="agent.completed",
                actor=role.value,
                payload={"task_id": str(task_id), "role": role.value, "tool": f"{server_name}.{tool_name}"},
                session_id=task.session_id,
                task_id=task.id,
            )
        await self._event_bus.publish(
            task_id,
            "step",
            {
                "ordinal": ordinal,
                "type": "tool_call",
                "description": description,
                "status": StepStatus.COMPLETED.value,
                "output": result,
                "agent_role": role.value,
            },
        )

    async def _record_guardrail_rejection(
        self,
        task_id: UUID,
        role: AgentRole,
        handoff: HandoffMessage,
        qualified_tool: str,
        agent_run_id: UUID,
    ) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while recording specialist rejection")
            agent_run = await session.get(AgentRun, agent_run_id)
            ordinal = await self._next_ordinal(session, task_id)
            task.status = TaskStatus.REJECTED
            task.error = f"Tool {qualified_tool} is outside the {role.value} scope."
            task.completed_at = datetime.now(UTC)
            session.add(
                TaskStep(
                    task_id=task_id,
                    ordinal=ordinal,
                    step_type=StepType.GUARDRAIL_BLOCK,
                    description=handoff["reason"],
                    status=StepStatus.SKIPPED,
                    agent_role=role,
                    attempt=1,
                    agent_run_id=agent_run_id,
                    input_json={"tool": qualified_tool, "payload": handoff["payload"]},
                    output_json={"message": f"Rejected out-of-scope tool {qualified_tool}."},
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
            if agent_run is not None:
                agent_run.status = AgentRunStatus.REJECTED
                agent_run.completed_at = datetime.now(UTC)
                agent_run.result_json = {"rejected_tool": qualified_tool}
            await session.commit()
            await self._audit_service.record_guardrail_event(
                session,
                event_type="guardrail.tool_disallowed",
                payload={"task_id": str(task_id), "role": role.value, "tool": qualified_tool},
                session_id=task.session_id,
                task_id=task.id,
            )
            await self._audit_service.record_event(
                session,
                event_type="agent.completed",
                actor=role.value,
                payload={"task_id": str(task_id), "role": role.value, "status": AgentRunStatus.REJECTED.value},
                session_id=task.session_id,
                task_id=task.id,
            )
        await self._event_bus.publish(task_id, "task_rejected", {"error": f"Tool {qualified_tool} is outside the {role.value} scope."})

    async def _create_agent_run(self, task_id: UUID, role: AgentRole, parent_run_id: UUID | None, handoff: HandoffMessage) -> UUID:
        async with self._session_factory() as session:
            agent_run = AgentRun(
                task_id=task_id,
                role=role,
                parent_run_id=parent_run_id,
                handoff_reason=handoff["reason"],
                handoff_payload_json=handoff["payload"],
                started_at=datetime.now(UTC),
                status=AgentRunStatus.RUNNING,
            )
            session.add(agent_run)
            await session.commit()
            task = await session.get(Task, task_id)
            if task is not None:
                await self._audit_service.record_event(
                    session,
                    event_type="agent.handoff",
                    actor=AgentRole.ORCHESTRATOR.value,
                    payload={"task_id": str(task_id), "to": role.value, "reason": handoff["reason"]},
                    session_id=task.session_id,
                    task_id=task.id,
                )
            return agent_run.id

    async def _finalize_agent_run(self, agent_run_id: UUID, result: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            agent_run = await session.get(AgentRun, agent_run_id)
            if agent_run is None or agent_run.status == AgentRunStatus.REJECTED:
                return
            agent_run.status = AgentRunStatus.COMPLETED
            agent_run.completed_at = datetime.now(UTC)
            agent_run.result_json = result
            await session.commit()
            if agent_run.role != AgentRole.ORCHESTRATOR:
                orchestrator_run = await self._latest_run(session, agent_run.task_id, AgentRole.ORCHESTRATOR)
                if orchestrator_run is not None:
                    orchestrator_run.status = AgentRunStatus.HANDED_OFF
                    await session.commit()

    async def _latest_run_id(self, task_id: UUID, role: AgentRole) -> UUID | None:
        async with self._session_factory() as session:
            agent_run = await self._latest_run(session, task_id, role)
            return agent_run.id if agent_run is not None else None

    async def _latest_run(self, session: AsyncSession, task_id: UUID, role: AgentRole) -> AgentRun | None:
        rows = list(
            (
                await session.execute(
                    select(AgentRun)
                    .where(AgentRun.task_id == task_id, AgentRun.role == role)
                    .order_by(AgentRun.started_at.asc()),
                )
            ).scalars()
        )
        return rows[-1] if rows else None

    async def _next_ordinal(self, session: AsyncSession, task_id: UUID) -> int:
        current_max = (
            await session.execute(
                select(func.max(TaskStep.ordinal)).where(TaskStep.task_id == task_id),
            )
        ).scalar_one()
        return int(current_max or 0) + 1

    async def _finalize_orchestrator_run(self, task_id: UUID, result: dict[str, Any], status: AgentRunStatus) -> None:
        async with self._session_factory() as session:
            agent_run = await self._latest_run(session, task_id, AgentRole.ORCHESTRATOR)
            if agent_run is None:
                return
            agent_run.status = status
            agent_run.completed_at = datetime.now(UTC)
            agent_run.result_json = result
            await session.commit()

    @staticmethod
    def _server_for_role(role: AgentRole) -> str:
        return {
            AgentRole.ANALYST: "sqlite_query",
            AgentRole.RESEARCHER: "file_search",
            AgentRole.ENGINEER: "github",
        }.get(role, "")
