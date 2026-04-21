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
from agentforge.models.approval import ApprovalDecision, RiskLevel
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.models.tool_call import ToolCall
from agentforge.schemas.task import PlanStep
from agentforge.services.approval_service import ApprovalService, RiskAssessment
from agentforge.services.audit_service import AuditService
from agentforge.services.mcp_client_pool import MCPClientPool
from agentforge.services.self_healing import SelfHealingOutcome, SelfHealingWrapper
from agentforge.services.skills_registry import SkillContext, SkillsRegistry, _get_or_create_skills_registry
from agentforge.services.task_event_bus import TaskEventBus


@dataclass(slots=True)
class SupervisorExecutionResult:
    supervisor_plan: dict[str, Any]
    final_response: str
    rejected: bool = False
    awaiting_approval: bool = False
    error: str | None = None


class SupervisorGraph:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        mcp_pool: MCPClientPool,
        event_bus: TaskEventBus,
        audit_service: AuditService,
        approval_service: ApprovalService,
        llm_provider,
        skills_registry: SkillsRegistry | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._mcp_pool = mcp_pool
        self._event_bus = event_bus
        self._audit_service = audit_service
        self._approval_service = approval_service
        self._self_healing = SelfHealingWrapper(llm_provider)
        self._orchestrator = OrchestratorAgent(llm_provider)
        self._skills_registry = skills_registry or _get_or_create_skills_registry(session_factory=session_factory)

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
            task.plan = supervisor_plan
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
            existing_result = await self._get_completed_specialist_result(task_id, role, handoff)
            if existing_result is not None:
                specialist_results.append(existing_result)
                continue

            await self._event_bus.publish(
                task_id,
                "agent_handoff",
                {"from": AgentRole.ORCHESTRATOR.value, "to": role.value, "reason": handoff["reason"]},
            )
            agent_run_id = await self._create_agent_run(task_id, role, orchestrator_run_id, handoff)
            specialist_result = await self._run_specialist(task_id, user_prompt, role, handoff, agent_run_id)
            specialist_results.append(specialist_result)

            if specialist_result.get("awaiting_approval"):
                await self._finalize_orchestrator_run(task_id, supervisor_plan, AgentRunStatus.HANDED_OFF)
                return SupervisorExecutionResult(
                    supervisor_plan=supervisor_plan,
                    final_response="",
                    awaiting_approval=True,
                )

            if specialist_result.get("rejected"):
                await self._finalize_orchestrator_run(task_id, supervisor_plan, AgentRunStatus.REJECTED)
                return SupervisorExecutionResult(
                    supervisor_plan=supervisor_plan,
                    final_response="",
                    rejected=True,
                    error=str(specialist_result["summary"]),
                )
            await self._finalize_agent_run(agent_run_id, specialist_result)

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

    async def resume_after_approval(self, task_id: UUID, approval_id: UUID) -> bool:
        async with self._session_factory() as session:
            approval = await self._approval_service.get_by_id(session, approval_id)
            task = await session.get(Task, task_id)
            if approval is None or task is None:
                raise RuntimeError("Approval state missing during supervisor resume")

            if approval.decision == ApprovalDecision.REJECTED:
                rejection_reason, _ = await self._approval_service.apply_rejection(session, approval)
                await session.commit()
                await self._event_bus.publish(
                    task_id,
                    "task_rejected",
                    {"error": rejection_reason, "approval_id": str(approval.id)},
                )
                return False

            await self._approval_service.mark_gate_approved(session, approval)
            await session.commit()

        await self._event_bus.publish(
            task_id,
            "approval_resumed",
            {"approval_id": str(approval_id), "decision": ApprovalDecision.APPROVED.value},
        )
        return True

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
        task_context = await self._load_skill_context(
            task_id=task_id,
            user_prompt=user_prompt,
            role=role,
            handoff=handoff,
        )
        if qualified_tool not in allowed_tools:
            await self._record_guardrail_rejection(task_id, role, handoff, qualified_tool, agent_run_id)
            return {
                "role": role.value,
                "summary": f"{role.value} attempted out-of-scope tool {qualified_tool} and was rejected.",
                "data": {"rejected_tool": qualified_tool},
                "rejected": True,
            }

        await self._skills_registry.ensure_loaded()
        skill = self._skills_registry.get_skill_for_role(role)
        evaluation = self._skills_registry.evaluate(
            skill=skill,
            tool_name=qualified_tool,
            args=request.args,
            task_context=task_context,
        )

        if not evaluation.allowed:
            await self._record_skill_policy_step(
                task_id=task_id,
                role=role,
                handoff=handoff,
                qualified_tool=qualified_tool,
                reason=evaluation.violation_reason or "Skill policy blocked the request.",
                agent_run_id=agent_run_id,
                suggested_role=evaluation.reroute_role,
            )
            await self._skills_registry.record_policy_violation(
                task_id=task_id,
                session_id=task_context.session_id,
                role=role,
                skill=skill,
                tool_name=qualified_tool,
                reason=evaluation.violation_reason or "Skill policy blocked the request.",
                policy_checks=evaluation.policy_checks,
            )
            if evaluation.reroute_role is not None:
                reroute_handoff: HandoffMessage = {
                    "to": evaluation.reroute_role.value,
                    "reason": f"Skill policy rerouted: {handoff['reason']}",
                    "payload": dict(handoff["payload"]),
                }
                await self._event_bus.publish(
                    task_id,
                    "agent_handoff",
                    {
                        "from": role.value,
                        "to": evaluation.reroute_role.value,
                        "reason": evaluation.violation_reason or "Skill topic scope mismatch.",
                    },
                )
                reroute_run_id = await self._create_agent_run(task_id, evaluation.reroute_role, agent_run_id, reroute_handoff)
                return await self._run_specialist(
                    task_id,
                    user_prompt,
                    evaluation.reroute_role,
                    reroute_handoff,
                    reroute_run_id,
                )
            return {
                "role": role.value,
                "summary": evaluation.violation_reason or f"{role.value} was blocked by skill policy.",
                "data": {"policy_checks": evaluation.policy_checks},
                "rejected": True,
            }

        step = PlanStep(
            step_id=f"{role.value}-{server_name}-{tool_name}",
            type="tool_call",
            description=request.description,
            server=server_name,
            tool=tool_name,
            args=request.args,
        )
        if evaluation.requires_approval:
            approval_id = await self._request_skill_policy_approval(
                task_id=task_id,
                step=step,
                role=role,
                reason=evaluation.approval_reason or f"Skill {skill.name} requires approval.",
                summary=request.description,
            )
            return {
                "role": role.value,
                "summary": evaluation.approval_reason or f"{role.value} is awaiting operator approval.",
                "data": {"approval_id": approval_id},
                "awaiting_approval": True,
            }

        evaluation.policy_checks["rate_limit"] = await self._skills_registry.await_rate_limit(skill)
        healing = await self._self_healing.execute(
            step=step,
            input_payload={"server": server_name, "tool": tool_name, "args": request.args},
            execute_fn=lambda: self._mcp_pool.call_tool(server_name, tool_name, request.args),
            user_prompt=user_prompt,
            last_output=None,
            kind="tool_call",
        )

        history_root_step_id = await self._record_history_entries(task_id, role, step, healing.history_entries, agent_run_id)
        await self._record_retry_events(task_id, role, step.step_id, healing.retry_events, agent_run_id)

        if healing.needs_approval:
            approval_id = await self._request_operator_review(task_id, step, role, healing, handoff)
            return {
                "role": role.value,
                "summary": healing.approval_summary or f"{role.value} is awaiting operator approval after repeated failure.",
                "data": {"approval_id": approval_id},
                "awaiting_approval": True,
            }

        if healing.error and healing.output is None:
            await self._record_terminal_failure(task_id, role, step, healing, agent_run_id, history_root_step_id)
            return {
                "role": role.value,
                "summary": f"{role.value} failed while executing {qualified_tool}.",
                "data": {"error": healing.error},
                "rejected": True,
            }

        dispatch_result = self._skills_registry.apply_post_policies(
            skill=skill,
            result=healing.output,
            prior_checks=evaluation.policy_checks,
        )
        summary = SpecialistSummarizer.summarize(role, dispatch_result.agent_result)
        task_step_id = await self._record_tool_step(
            task_id=task_id,
            role=role,
            step=step,
            result=dispatch_result.step_output,
            agent_run_id=agent_run_id,
            attempt=healing.attempt,
            step_type=healing.step_type_override or StepType.TOOL_CALL,
            parent_step_id=history_root_step_id if healing.parent_to_history_root else None,
        )
        await self._skills_registry.record_invocation(
            task_step_id=task_step_id,
            task_id=task_id,
            session_id=task_context.session_id,
            skill=skill,
            policy_checks=dispatch_result.policy_checks,
            injected_knowledge_tokens=dispatch_result.injected_knowledge_tokens,
        )
        await self._event_bus.publish(
            task_id,
            "skill_invoked",
            {
                "role": role.value,
                "skill_name": skill.name,
                "task_step_id": str(task_step_id),
            },
        )
        return {"role": role.value, "summary": summary, "data": dispatch_result.agent_result}

    async def _record_tool_step(
        self,
        *,
        task_id: UUID,
        role: AgentRole,
        step: PlanStep,
        result: Any,
        agent_run_id: UUID,
        attempt: int,
        step_type: StepType,
        parent_step_id: UUID | None,
    ) -> UUID:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while recording specialist step")
            ordinal = await self._next_ordinal(session, task_id)
            task_step = TaskStep(
                task_id=task_id,
                ordinal=ordinal,
                step_type=step_type,
                description=step.description,
                status=StepStatus.COMPLETED,
                agent_role=role,
                attempt=attempt,
                parent_step_id=parent_step_id,
                agent_run_id=agent_run_id,
                input_json={"server": step.server, "tool": step.tool, "args": step.args},
                output_json=result,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            session.add(task_step)
            await session.flush()
            session.add(
                ToolCall(
                    task_step_id=task_step.id,
                    server_name=step.server or "",
                    tool_name=step.tool or "",
                    arguments_json=step.args,
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
                payload={"task_id": str(task_id), "role": role.value, "tool": f"{step.server}.{step.tool}"},
                session_id=task.session_id,
                task_id=task.id,
            )
        await self._event_bus.publish(
            task_id,
            "step",
            {
                "ordinal": ordinal,
                "type": step_type.value,
                "description": step.description,
                "status": StepStatus.COMPLETED.value,
                "output": result,
                "agent_role": role.value,
            },
        )
        return task_step.id

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

    async def _record_history_entries(
        self,
        task_id: UUID,
        role: AgentRole,
        step: PlanStep,
        history_entries: list[dict[str, Any]],
        agent_run_id: UUID,
    ) -> UUID | None:
        if not history_entries:
            return None

        history_root_step_id: UUID | None = None
        async with self._session_factory() as session:
            for entry in history_entries:
                task_step = TaskStep(
                    task_id=task_id,
                    ordinal=await self._next_ordinal(session, task_id),
                    step_type=entry["step_type"],
                    description=entry["description"],
                    status=entry["status"],
                    agent_role=role,
                    attempt=int(entry.get("attempt", 1)),
                    parent_step_id=history_root_step_id if entry.get("link_to_history_root") else None,
                    agent_run_id=agent_run_id,
                    input_json=entry.get("input_json"),
                    output_json=entry.get("output_json"),
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
                session.add(task_step)
                await session.flush()
                if history_root_step_id is None:
                    history_root_step_id = task_step.id

                if entry["step_type"] in {StepType.TOOL_CALL, StepType.RETRY}:
                    session.add(
                        ToolCall(
                            task_step_id=task_step.id,
                            server_name=step.server or "",
                            tool_name=step.tool or "",
                            arguments_json=step.args,
                            result_json=entry.get("output_json"),
                            error=(entry.get("output_json") or {}).get("error") if isinstance(entry.get("output_json"), dict) else None,
                            duration_ms=0,
                            required_approval=False,
                            started_at=task_step.started_at,
                            completed_at=task_step.completed_at,
                        )
                    )
            await session.commit()
        return history_root_step_id

    async def _record_retry_events(
        self,
        task_id: UUID,
        role: AgentRole,
        step_id: str,
        retry_events: list[dict[str, Any]],
        agent_run_id: UUID,
    ) -> None:
        if not retry_events:
            return

        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while recording specialist retry event")
            reflection_present = bool(
                (
                    await session.execute(
                        select(func.count()).select_from(TaskStep).where(
                            TaskStep.task_id == task_id,
                            TaskStep.agent_role == role,
                            TaskStep.step_type == StepType.REFLECTION,
                        ),
                    )
                ).scalar_one()
            )
            for retry_event in retry_events:
                if not reflection_present:
                    session.add(
                        TaskStep(
                            task_id=task_id,
                            ordinal=await self._next_ordinal(session, task_id),
                            step_type=StepType.REFLECTION,
                            description=f"Reflect on failure in {step_id}",
                            status=StepStatus.COMPLETED,
                            agent_role=role,
                            attempt=max(1, int(retry_event["attempt"]) - 1),
                            agent_run_id=agent_run_id,
                            input_json={"step_id": step_id},
                            output_json={"text": f"Retry triggered after failure: {retry_event['error']}"},
                            started_at=datetime.now(UTC),
                            completed_at=datetime.now(UTC),
                        )
                    )
                    reflection_present = True
                session.add(
                    TaskStep(
                        task_id=task_id,
                        ordinal=await self._next_ordinal(session, task_id),
                        step_type=StepType.RETRY,
                        description=f"Retry {retry_event['attempt']} for {step_id}",
                        status=StepStatus.COMPLETED,
                        agent_role=role,
                        attempt=int(retry_event["attempt"]),
                        agent_run_id=agent_run_id,
                        input_json={"step_id": step_id},
                        output_json={"error": retry_event["error"]},
                        started_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                    )
                )
                await self._audit_service.record_event(
                    session,
                    event_type="agent.retry",
                    actor=role.value,
                    payload={
                        "task_id": str(task_id),
                        "step_id": step_id,
                        "attempt": retry_event["attempt"],
                        "error": retry_event["error"],
                        "role": role.value,
                    },
                    session_id=task.session_id,
                    task_id=task.id,
                )
                await self._event_bus.publish(
                    task_id,
                    "agent_retry",
                    {"step_id": step_id, "attempt": retry_event["attempt"], "error": retry_event["error"], "agent_role": role.value},
                )

    async def _record_terminal_failure(
        self,
        task_id: UUID,
        role: AgentRole,
        step: PlanStep,
        healing: SelfHealingOutcome,
        agent_run_id: UUID,
        history_root_step_id: UUID | None,
    ) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            agent_run = await session.get(AgentRun, agent_run_id)
            if task is None:
                raise RuntimeError("Task not found while recording specialist failure")
            ordinal = await self._next_ordinal(session, task_id)
            task.status = TaskStatus.FAILED
            task.error = healing.error
            task.completed_at = datetime.now(UTC)
            session.add(
                TaskStep(
                    task_id=task_id,
                    ordinal=ordinal,
                    step_type=healing.step_type_override or StepType.TOOL_CALL,
                    description=step.description,
                    status=StepStatus.FAILED,
                    agent_role=role,
                    attempt=healing.attempt,
                    parent_step_id=history_root_step_id if healing.parent_to_history_root else None,
                    agent_run_id=agent_run_id,
                    input_json={"server": step.server, "tool": step.tool, "args": step.args},
                    output_json={"error": healing.error},
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
            if agent_run is not None:
                agent_run.status = AgentRunStatus.FAILED
                agent_run.completed_at = datetime.now(UTC)
                agent_run.result_json = {"error": healing.error}
            await session.commit()
            await self._audit_service.record_event(
                session,
                event_type="task.failed",
                actor=role.value,
                payload={"task_id": str(task_id), "step_id": step.step_id, "error": healing.error},
                session_id=task.session_id,
                task_id=task.id,
            )
        await self._event_bus.publish(task_id, "task_failed", {"error": healing.error})

    async def _load_skill_context(
        self,
        *,
        task_id: UUID,
        user_prompt: str,
        role: AgentRole,
        handoff: HandoffMessage,
    ) -> SkillContext:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while building skill context")
            return SkillContext(
                task_id=task_id,
                session_id=task.session_id,
                user_prompt=user_prompt,
                handoff_reason=handoff["reason"],
                handoff_payload=handoff["payload"],
                agent_role=role,
            )

    async def _record_skill_policy_step(
        self,
        *,
        task_id: UUID,
        role: AgentRole,
        handoff: HandoffMessage,
        qualified_tool: str,
        reason: str,
        agent_run_id: UUID,
        suggested_role: AgentRole | None,
    ) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while recording skill policy step")
            session.add(
                TaskStep(
                    task_id=task_id,
                    ordinal=await self._next_ordinal(session, task_id),
                    step_type=StepType.GUARDRAIL_BLOCK,
                    description=reason,
                    status=StepStatus.SKIPPED,
                    agent_role=role,
                    attempt=1,
                    agent_run_id=agent_run_id,
                    input_json={"tool": qualified_tool, "payload": handoff["payload"]},
                    output_json={"rerouted_to": suggested_role.value if suggested_role else None},
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def _request_skill_policy_approval(
        self,
        *,
        task_id: UUID,
        step: PlanStep,
        role: AgentRole,
        reason: str,
        summary: str,
    ) -> str:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while requesting skill policy approval")
            context = await self._approval_service.ensure_approval(
                session,
                task=task,
                step=step,
                assessment=RiskAssessment(
                    risk_level=RiskLevel.MEDIUM,
                    reason=reason,
                    summary=summary,
                ),
                checkpoint_id=str(task_id),
            )
            approval_id = str(context.approval.id)

        if context.created:
            await self._event_bus.publish(
                task_id,
                "approval_requested",
                {
                    "approval_id": approval_id,
                    "risk_level": context.assessment.risk_level.value,
                    "risk_reason": context.assessment.reason,
                    "action_summary": context.assessment.summary,
                },
            )
        return approval_id

    async def _request_operator_review(
        self,
        task_id: UUID,
        step: PlanStep,
        role: AgentRole,
        healing: SelfHealingOutcome,
        handoff: HandoffMessage,
    ) -> str:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise RuntimeError("Task not found while requesting specialist approval")
            context = await self._approval_service.ensure_approval(
                session,
                task=task,
                step=step,
                assessment=RiskAssessment(
                    risk_level=RiskLevel.MEDIUM,
                    reason=healing.approval_reason or f"{role.value} exhausted retries.",
                    summary=healing.approval_summary or handoff["reason"],
                ),
                checkpoint_id=str(task_id),
            )
            approval_id = str(context.approval.id)

        if context.created:
            await self._event_bus.publish(
                task_id,
                "approval_requested",
                {
                    "approval_id": approval_id,
                    "risk_level": context.assessment.risk_level.value,
                    "risk_reason": context.assessment.reason,
                    "action_summary": context.assessment.summary,
                },
            )
        return approval_id

    async def _get_completed_specialist_result(
        self,
        task_id: UUID,
        role: AgentRole,
        handoff: HandoffMessage,
    ) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            run = (
                await session.execute(
                    select(AgentRun)
                    .where(
                        AgentRun.task_id == task_id,
                        AgentRun.role == role,
                        AgentRun.status == AgentRunStatus.COMPLETED,
                        AgentRun.handoff_reason == handoff["reason"],
                        AgentRun.handoff_payload_json == handoff["payload"],
                    )
                    .order_by(AgentRun.started_at.desc()),
                )
            ).scalars().first()
        if run is None or not isinstance(run.result_json, dict):
            return None
        return run.result_json

    @staticmethod
    def _server_for_role(role: AgentRole) -> str:
        return {
            AgentRole.ANALYST: "sqlite_query",
            AgentRole.RESEARCHER: "file_search",
            AgentRole.ENGINEER: "github",
        }.get(role, "")
