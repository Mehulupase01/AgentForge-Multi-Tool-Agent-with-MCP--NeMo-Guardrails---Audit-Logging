from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.config import settings
from agentforge.guardrails.runner import GuardrailsRunner
from agentforge.models.approval import ApprovalDecision, RiskLevel
from agentforge.models.llm_call import LLMCall
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import StepStatus, StepType, TaskStep
from agentforge.models.tool_call import ToolCall
from agentforge.schemas.task import PlanStep
from agentforge.services.approval_service import ApprovalService, get_approval_service
from agentforge.services.audit_service import AuditService
from agentforge.services.llm_provider import LLMProvider
from agentforge.services.mcp_client_pool import MCPClientPool
from agentforge.services.task_event_bus import TaskEventBus


class AgentState(TypedDict, total=False):
    task_id: str
    user_prompt: str
    input_rails: dict[str, Any] | None
    plan: list[dict[str, Any]] | None
    cursor: int
    last_output: dict[str, Any] | None
    final_response: str | None
    error: str | None
    rejected: bool
    current_step: dict[str, Any] | None
    current_result: dict[str, Any] | None


class AgentOrchestrator:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        mcp_pool: MCPClientPool,
        llm_provider: LLMProvider,
        event_bus: TaskEventBus,
        guardrails_runner: GuardrailsRunner,
        approval_service: ApprovalService,
        audit_service: AuditService | None = None,
        checkpoint_path: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._mcp_pool = mcp_pool
        self._llm_provider = llm_provider
        self._event_bus = event_bus
        self._guardrails_runner = guardrails_runner
        self._approval_service = approval_service
        self._audit_service = audit_service or AuditService()
        self._checkpoint_path = checkpoint_path or settings.orchestrator_checkpoint_path
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_inputs: dict[str, dict[str, Any]] = {}
        self._graph: Any | None = None
        self._checkpointer_cm: Any | None = None
        self._graph_lock = asyncio.Lock()

    async def _ensure_graph(self):
        if self._graph is not None:
            return self._graph

        async with self._graph_lock:
            if self._graph is not None:
                return self._graph

            checkpoint_path = Path(self._checkpoint_path)
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self._checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
            checkpointer = await self._checkpointer_cm.__aenter__()
            self._graph = self._build_graph(checkpointer)
            return self._graph

    def _build_graph(self, checkpointer: AsyncSqliteSaver):
        graph = StateGraph(AgentState)
        graph.add_node("plan_node", self._plan)
        graph.add_node("next_step_node", self._next_step)
        graph.add_node("execute_step_node", self._execute_step)
        graph.add_node("record_step_node", self._record_step)
        graph.add_node("finalize_node", self._finalize)

        graph.add_edge(START, "plan_node")
        graph.add_edge("plan_node", "next_step_node")
        graph.add_conditional_edges(
            "next_step_node",
            self._route_after_next_step,
            {"execute_step_node": "execute_step_node", "finalize_node": "finalize_node"},
        )
        graph.add_edge("execute_step_node", "record_step_node")
        graph.add_conditional_edges(
            "record_step_node",
            self._route_after_record_step,
            {"next_step_node": "next_step_node", "finalize_node": "finalize_node"},
        )
        graph.add_edge("finalize_node", END)
        return graph.compile(checkpointer=checkpointer)

    def start_task(
        self,
        task_id: UUID,
        *,
        input_rails: dict[str, Any] | None = None,
        resume_approval_id: UUID | None = None,
    ) -> None:
        task_key = str(task_id)
        if task_key in self._tasks and not self._tasks[task_key].done():
            return
        if input_rails is not None:
            self._pending_inputs[task_key] = input_rails
        background = asyncio.create_task(self._run_task(task_key, resume_approval_id=str(resume_approval_id) if resume_approval_id else None))
        self._tasks[task_key] = background
        background.add_done_callback(lambda _: (self._tasks.pop(task_key, None), self._pending_inputs.pop(task_key, None)))

    async def resume_task(self, task_id: UUID) -> bool:
        async with self._session_factory() as session:
            approval = await self._approval_service.get_latest_decided_for_task(session, task_id)
        if approval is None:
            return False

        task_key = str(task_id)
        if task_key in self._tasks and not self._tasks[task_key].done():
            await self._approval_service.signal_resume(task_id, approval.id)
            return True

        self.start_task(task_id, resume_approval_id=approval.id)
        return True

    async def close(self) -> None:
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        await self._approval_service.close()
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer_cm = None
        self._graph = None

    async def _run_task(self, task_id: str, *, resume_approval_id: str | None = None) -> None:
        await asyncio.sleep(0.05)
        graph = await self._ensure_graph()
        config = {"configurable": {"thread_id": task_id}}

        if resume_approval_id is None:
            current_input: AgentState | Command = await self._load_initial_state(task_id)
        else:
            current_input = Command(resume={"approval_id": resume_approval_id})

        try:
            while True:
                await graph.ainvoke(current_input, config=config)
                snapshot = await graph.aget_state(config)
                if snapshot.next and any(task.interrupts for task in snapshot.tasks):
                    approval_id = await self._approval_service.wait_for_resume(task_id)
                    current_input = Command(resume={"approval_id": approval_id})
                    continue
                break
        except Exception as exc:
            await self._fail_task(task_id, str(exc), step_id="plan")

    async def _load_initial_state(self, task_id: str) -> AgentState:
        async with self._session_factory() as session:
            task = await session.get(Task, UUID(task_id))
            if task is None:
                raise RuntimeError("Task not found during startup")
            user_prompt = task.user_prompt
            input_rails = self._pending_inputs.pop(task_id, {"pii": {"redacted": False, "entities": []}})

        return {
            "task_id": task_id,
            "user_prompt": user_prompt,
            "plan": None,
            "cursor": 0,
            "last_output": None,
            "final_response": None,
            "error": None,
            "rejected": False,
            "input_rails": input_rails,
        }

    async def _plan(self, state: AgentState) -> AgentState:
        response = await self._llm_provider.generate_plan(state["user_prompt"])
        parsed = self._parse_plan(response.text)

        async with self._session_factory() as session:
            task = await session.get(Task, UUID(state["task_id"]))
            if task is None:
                raise RuntimeError("Task not found during planning")

            task.plan = [step.model_dump() for step in parsed]
            task.status = TaskStatus.EXECUTING
            task.started_at = datetime.now(UTC)
            session.add(
                LLMCall(
                    provider=self._llm_provider.provider_name,
                    model=self._llm_provider.model_name,
                    prompt=state["user_prompt"],
                    completion=response.text,
                    input_rails_json=state.get("input_rails"),
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                ),
            )
            await session.commit()

            await self._audit_service.record_event(
                session,
                event_type="task.planned",
                actor="system",
                payload={"task_id": state["task_id"], "step_count": len(parsed)},
                session_id=task.session_id,
                task_id=task.id,
            )

        await self._event_bus.publish(
            state["task_id"],
            "plan",
            {"steps": [step.model_dump() for step in parsed]},
        )
        return {**state, "plan": [step.model_dump() for step in parsed], "cursor": 0}

    async def _next_step(self, state: AgentState) -> AgentState:
        plan = state.get("plan") or []
        cursor = state.get("cursor", 0)
        if cursor >= len(plan):
            return {**state, "current_step": None}
        return {**state, "current_step": plan[cursor]}

    def _route_after_next_step(self, state: AgentState) -> str:
        return "finalize_node" if state.get("current_step") is None else "execute_step_node"

    async def _execute_step(self, state: AgentState) -> AgentState:
        step = PlanStep.model_validate(state["current_step"])
        started = perf_counter()
        try:
            if step.type == "tool_call":
                tool_check = self._guardrails_runner.check_tool(step.server or "", step.tool or "")
                if not tool_check.allowed:
                    return {
                        **state,
                        "current_result": {
                            "status": StepStatus.SKIPPED.value,
                            "kind": "guardrail_block",
                            "output": {"message": tool_check.reason},
                            "input": {"server": step.server, "tool": step.tool, "args": step.args},
                            "guardrail": {
                                "event_type": "guardrail.tool_disallowed",
                                "detail": tool_check.detail,
                            },
                            "duration_ms": int((perf_counter() - started) * 1000),
                        },
                    }

                assessment = self._approval_service.classify_tool_call(step)
                approval_id: str | None = None
                if assessment.requires_approval:
                    async with self._session_factory() as session:
                        task = await session.get(Task, UUID(state["task_id"]))
                        if task is None:
                            raise RuntimeError("Task not found during approval request")
                        approval_context = await self._approval_service.ensure_approval(
                            session,
                            task=task,
                            step=step,
                            assessment=assessment,
                            checkpoint_id=state["task_id"],
                        )
                        approval_id = str(approval_context.approval.id)

                    if approval_context.created:
                        await self._event_bus.publish(
                            state["task_id"],
                            "approval_requested",
                            {
                                "approval_id": approval_id,
                                "risk_level": assessment.risk_level.value,
                                "risk_reason": assessment.reason,
                                "action_summary": assessment.summary,
                            },
                        )

                    interrupt(
                        {
                            "approval_id": approval_id,
                            "risk_level": assessment.risk_level.value,
                            "risk_reason": assessment.reason,
                            "action_summary": assessment.summary,
                        }
                    )

                    async with self._session_factory() as session:
                        approval = await self._approval_service.get_by_id(session, UUID(approval_id))
                        if approval is None:
                            raise RuntimeError("Approval record disappeared before resume")
                        if approval.decision == ApprovalDecision.REJECTED:
                            return {
                                **state,
                                "error": approval.rationale or approval.risk_reason,
                                "rejected": True,
                                "current_result": {
                                    "status": StepStatus.FAILED.value,
                                    "kind": "approval_gate",
                                    "output": {
                                        "message": approval.rationale or approval.risk_reason,
                                        "decision": approval.decision.value,
                                    },
                                    "input": {"server": step.server, "tool": step.tool, "args": step.args},
                                    "approval": {"approval_id": str(approval.id)},
                                    "duration_ms": int((perf_counter() - started) * 1000),
                                },
                            }
                        await self._approval_service.mark_gate_approved(session, approval)
                        await session.commit()
                    await self._event_bus.publish(
                        state["task_id"],
                        "approval_resumed",
                        {"approval_id": approval_id, "decision": ApprovalDecision.APPROVED.value},
                    )

                result = await self._mcp_pool.call_tool(step.server or "", step.tool or "", step.args)
                return {
                    **state,
                    "current_result": {
                        "status": StepStatus.COMPLETED.value,
                        "kind": "tool_call",
                        "output": result,
                        "input": {"server": step.server, "tool": step.tool, "args": step.args},
                        "approval": {"approval_id": approval_id} if approval_id else None,
                        "duration_ms": int((perf_counter() - started) * 1000),
                    },
                }

            if step.type == "llm_reasoning":
                prompt_payload = json.dumps(
                    {
                        "user_prompt": state["user_prompt"],
                        "step_description": step.description,
                        "last_output": state.get("last_output"),
                    },
                    ensure_ascii=True,
                )
                llm_response = await self._llm_provider.reason_step(prompt_payload)
                processed_output = self._guardrails_runner.process_output(llm_response.text)
                return {
                    **state,
                    "current_result": {
                        "status": StepStatus.COMPLETED.value,
                        "kind": "llm_reasoning",
                        "output": {"text": processed_output.text},
                        "input": {"prompt": prompt_payload},
                        "llm": {
                            "text": processed_output.text,
                            "prompt_tokens": llm_response.prompt_tokens,
                            "completion_tokens": llm_response.completion_tokens,
                            "latency_ms": llm_response.latency_ms,
                            "output_rails_json": processed_output.output_rails_json(),
                        },
                        "duration_ms": int((perf_counter() - started) * 1000),
                    },
                }

            return {
                **state,
                "current_result": {
                    "status": StepStatus.SKIPPED.value,
                    "kind": "approval_gate",
                    "output": {"message": "Approval gate step placeholder was skipped."},
                    "input": step.args,
                    "duration_ms": int((perf_counter() - started) * 1000),
                },
            }
        except GraphInterrupt:
            raise
        except Exception as exc:
            return {
                **state,
                "error": str(exc),
                "current_result": {
                    "status": StepStatus.FAILED.value,
                    "kind": step.type,
                    "error": str(exc),
                    "input": {"server": step.server, "tool": step.tool, "args": step.args},
                    "duration_ms": int((perf_counter() - started) * 1000),
                },
            }

    async def _record_step(self, state: AgentState) -> AgentState:
        step = PlanStep.model_validate(state["current_step"])
        result = state["current_result"] or {}
        now = datetime.now(UTC)

        async with self._session_factory() as session:
            task = await session.get(Task, UUID(state["task_id"]))
            if task is None:
                raise RuntimeError("Task not found during step recording")

            if result.get("kind") == "approval_gate":
                approval_payload = result.get("approval") or {}
                approval_id = approval_payload.get("approval_id")
                if approval_id is not None:
                    approval = await self._approval_service.get_by_id(session, UUID(approval_id))
                    if approval is not None:
                        rejection_reason, description = await self._approval_service.apply_rejection(session, approval)
                        gate_step = await session.get(TaskStep, approval.task_step_id) if approval.task_step_id is not None else None
                        await session.commit()
                        await self._event_bus.publish(
                            state["task_id"],
                            "step",
                            {
                                "ordinal": gate_step.ordinal if gate_step is not None else None,
                                "step_id": step.step_id,
                                "type": StepType.APPROVAL_GATE.value,
                                "description": description,
                                "status": StepStatus.FAILED.value,
                                "output": result.get("output"),
                                "error": rejection_reason,
                            },
                        )
                        await self._event_bus.publish(
                            state["task_id"],
                            "task_rejected",
                            {"error": rejection_reason, "approval_id": approval_id},
                        )
                        return {
                            **state,
                            "cursor": state.get("cursor", 0) + 1,
                            "error": rejection_reason,
                            "rejected": True,
                        }

            task_step = TaskStep(
                task_id=task.id,
                ordinal=await self._approval_service.next_ordinal(session, task.id),
                step_type=self._step_type_for(result.get("kind") or step.type),
                description=result.get("output", {}).get("message", step.description) if result.get("kind") == "guardrail_block" else step.description,
                status=StepStatus(result["status"]),
                input_json=result.get("input"),
                output_json=result.get("output"),
                started_at=now,
                completed_at=now,
            )
            session.add(task_step)
            await session.flush()

            if result.get("kind") == "tool_call":
                approval_payload = result.get("approval") or {}
                approval_id = approval_payload.get("approval_id")
                session.add(
                    ToolCall(
                        task_step_id=task_step.id,
                        server_name=step.server or "",
                        tool_name=step.tool or "",
                        arguments_json=step.args,
                        result_json=result.get("output"),
                        error=result.get("error"),
                        duration_ms=result.get("duration_ms"),
                        required_approval=approval_id is not None,
                        approval_id=UUID(approval_id) if approval_id else None,
                        started_at=now,
                        completed_at=now,
                    ),
                )
            elif result.get("kind") == "llm_reasoning":
                llm_response = result["llm"]
                session.add(
                    LLMCall(
                        task_step_id=task_step.id,
                        provider=self._llm_provider.provider_name,
                        model=self._llm_provider.model_name,
                        prompt=result["input"]["prompt"],
                        completion=llm_response["text"],
                        output_rails_json=llm_response.get("output_rails_json"),
                        prompt_tokens=llm_response["prompt_tokens"],
                        completion_tokens=llm_response["completion_tokens"],
                        latency_ms=llm_response["latency_ms"],
                    ),
                )
                if llm_response.get("output_rails_json", {}).get("pii", {}).get("redacted"):
                    await self._audit_service.record_guardrail_event(
                        session,
                        event_type="guardrail.output_blocked",
                        payload={"task_id": state["task_id"], "step_id": step.step_id},
                        session_id=task.session_id,
                        task_id=task.id,
                        commit=False,
                    )
            elif result.get("kind") == "guardrail_block":
                guardrail_event = result.get("guardrail", {})
                await self._audit_service.record_guardrail_event(
                    session,
                    event_type=guardrail_event.get("event_type", "guardrail.tool_disallowed"),
                    payload={"task_id": state["task_id"], "step_id": step.step_id, **guardrail_event.get("detail", {})},
                    session_id=task.session_id,
                    task_id=task.id,
                    commit=False,
                )

            if result["status"] == StepStatus.FAILED.value:
                task.status = TaskStatus.FAILED
                task.error = result.get("error") or state.get("error")
                task.completed_at = now
                await session.commit()

                await self._audit_service.record_event(
                    session,
                    event_type="task.failed",
                    actor="system",
                    payload={"task_id": state["task_id"], "step_id": step.step_id, "error": task.error},
                    session_id=task.session_id,
                    task_id=task.id,
                )
            else:
                await session.commit()

        await self._event_bus.publish(
            state["task_id"],
            "step",
            {
                "ordinal": task_step.ordinal,
                "step_id": step.step_id,
                "type": step.type,
                "description": step.description,
                "status": result["status"],
                "output": result.get("output"),
                "error": result.get("error"),
            },
        )

        last_output = state.get("last_output")
        if result.get("output") is not None:
            last_output = {"step_id": step.step_id, "type": step.type, "value": result["output"]}

        return {
            **state,
            "cursor": state.get("cursor", 0) + 1,
            "last_output": last_output,
            "rejected": state.get("rejected", False),
        }

    def _route_after_record_step(self, state: AgentState) -> str:
        return "finalize_node" if state.get("error") or state.get("rejected") else "next_step_node"

    async def _finalize(self, state: AgentState) -> AgentState:
        async with self._session_factory() as session:
            task = await session.get(Task, UUID(state["task_id"]))
            if task is None:
                raise RuntimeError("Task not found during finalization")

            if state.get("rejected"):
                return state

            if state.get("error"):
                await self._event_bus.publish(state["task_id"], "task_failed", {"error": state["error"]})
                return state

            final_response = self._render_final_response(state.get("last_output"))
            task.status = TaskStatus.COMPLETED
            task.final_response = final_response
            task.completed_at = datetime.now(UTC)
            await session.commit()

            await self._audit_service.record_event(
                session,
                event_type="task.completed",
                actor="system",
                payload={"task_id": state["task_id"], "final_response": final_response},
                session_id=task.session_id,
                task_id=task.id,
            )

        await self._event_bus.publish(state["task_id"], "task_completed", {"final_response": final_response})
        return {**state, "final_response": final_response}

    async def _fail_task(self, task_id: str, error: str, *, step_id: str) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, UUID(task_id))
            if task is None:
                return
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now(UTC)
            await session.commit()

            await self._audit_service.record_event(
                session,
                event_type="task.failed",
                actor="system",
                payload={"task_id": task_id, "step_id": step_id, "error": error},
                session_id=task.session_id,
                task_id=task.id,
            )

        await self._event_bus.publish(task_id, "task_failed", {"error": error})

    @staticmethod
    def _step_type_for(step_type: str) -> StepType:
        mapping = {
            "tool_call": StepType.TOOL_CALL,
            "llm_reasoning": StepType.LLM_REASONING,
            "approval_gate": StepType.APPROVAL_GATE,
            "guardrail_block": StepType.GUARDRAIL_BLOCK,
        }
        return mapping.get(step_type, StepType.LLM_REASONING)

    @staticmethod
    def _render_final_response(last_output: dict[str, Any] | None) -> str:
        if last_output is None:
            return "Task completed without producing any output."
        value = last_output.get("value")
        if isinstance(value, dict) and "text" in value:
            return str(value["text"])
        return json.dumps(value, ensure_ascii=True, indent=2)

    @staticmethod
    def _parse_plan(raw_text: str) -> list[PlanStep]:
        candidate = raw_text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if "\n" in candidate:
                candidate = candidate.split("\n", 1)[1]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            start_positions = [idx for idx in (candidate.find("{"), candidate.find("[")) if idx != -1]
            if not start_positions:
                raise
            start = min(start_positions)
            end = max(candidate.rfind("}"), candidate.rfind("]"))
            if end <= start:
                raise
            payload = json.loads(candidate[start : end + 1])
        steps = payload if isinstance(payload, list) else payload.get("steps", [])
        return [PlanStep.model_validate(step) for step in steps]


_agent_orchestrator: AgentOrchestrator | None = None


def get_agent_orchestrator(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    mcp_pool: MCPClientPool,
    llm_provider: LLMProvider,
    event_bus: TaskEventBus,
    guardrails_runner: GuardrailsRunner,
    approval_service: ApprovalService | None = None,
) -> AgentOrchestrator:
    global _agent_orchestrator
    if _agent_orchestrator is None:
        _agent_orchestrator = AgentOrchestrator(
            session_factory=session_factory,
            mcp_pool=mcp_pool,
            llm_provider=llm_provider,
            event_bus=event_bus,
            guardrails_runner=guardrails_runner,
            approval_service=approval_service or get_approval_service(),
        )
    return _agent_orchestrator
