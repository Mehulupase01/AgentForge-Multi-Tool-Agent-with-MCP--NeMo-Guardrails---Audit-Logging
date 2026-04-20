from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from agentforge.models.task_step import StepStatus, StepType
from agentforge.schemas.task import PlanStep
from agentforge.services.llm_provider import LLMProvider


@dataclass(slots=True)
class SelfHealingOutcome:
    status: StepStatus
    kind: str
    output: Any | None = None
    error: str | None = None
    attempt: int = 1
    step_type_override: StepType | None = None
    parent_to_history_root: bool = False
    history_entries: list[dict[str, Any]] = field(default_factory=list)
    retry_events: list[dict[str, Any]] = field(default_factory=list)
    needs_approval: bool = False
    approval_reason: str | None = None
    approval_summary: str | None = None


class SelfHealingWrapper:
    def __init__(self, llm_provider: LLMProvider, *, sleep_fn: Callable[[float], Awaitable[None]] | None = None) -> None:
        self._llm_provider = llm_provider
        self._sleep = sleep_fn or (lambda _: asyncio.sleep(0))

    async def execute(
        self,
        *,
        step: PlanStep,
        input_payload: dict[str, Any],
        execute_fn: Callable[[], Awaitable[Any]],
        user_prompt: str,
        last_output: dict[str, Any] | None,
        kind: str,
    ) -> SelfHealingOutcome:
        attempt = 1
        history_entries: list[dict[str, Any]] = []
        retry_events: list[dict[str, Any]] = []
        classification = "unknown"
        last_error = ""

        while True:
            try:
                output = await execute_fn()
                return SelfHealingOutcome(
                    status=StepStatus.COMPLETED,
                    kind=kind,
                    output=output,
                    attempt=attempt,
                    step_type_override=StepType.RETRY if attempt > 1 else None,
                    parent_to_history_root=attempt > 1,
                    history_entries=history_entries,
                    retry_events=retry_events,
                )
            except Exception as exc:
                last_error = str(exc)
                classification = self._classify_error(kind, exc)
                history_entries.append(
                    {
                        "step_type": StepType.TOOL_CALL if kind == "tool_call" else StepType.LLM_REASONING,
                        "status": StepStatus.FAILED,
                        "description": step.description,
                        "attempt": attempt,
                        "input_json": input_payload,
                        "output_json": {"error": last_error, "classification": classification},
                    }
                )

                if classification == "guardrail":
                    return SelfHealingOutcome(
                        status=StepStatus.FAILED,
                        kind=kind,
                        error=last_error,
                        attempt=attempt,
                        history_entries=history_entries,
                        retry_events=retry_events,
                    )

                max_attempts = {"transient": 3, "validation": 3, "llm": 2, "unknown": 2}[classification]
                if attempt >= max_attempts:
                    if classification in {"transient", "validation", "llm"}:
                        return SelfHealingOutcome(
                            status=StepStatus.FAILED,
                            kind="approval_gate",
                            error=last_error,
                            attempt=attempt,
                            history_entries=history_entries,
                            retry_events=retry_events,
                            needs_approval=True,
                            approval_reason=f"Self-healing exhausted retries after {classification} failure: {last_error}",
                            approval_summary=f"{step.description} requires operator review after repeated failure.",
                        )
                    return SelfHealingOutcome(
                        status=StepStatus.FAILED,
                        kind=kind,
                        error=last_error,
                        attempt=attempt,
                        step_type_override=StepType.RETRY if attempt > 1 else None,
                        parent_to_history_root=attempt > 1,
                        history_entries=history_entries,
                        retry_events=retry_events,
                    )

                reflection_input = {
                    "user_prompt": user_prompt,
                    "step_description": step.description,
                    "step_args": input_payload,
                    "prior_error": last_error,
                    "last_output": last_output,
                }
                reflection_text = await self._reflect(reflection_input)
                history_entries.append(
                    {
                        "step_type": StepType.REFLECTION,
                        "status": StepStatus.COMPLETED,
                        "description": f"Reflect on failure in {step.step_id}",
                        "attempt": attempt,
                        "link_to_history_root": True,
                        "input_json": reflection_input,
                        "output_json": {"text": reflection_text},
                        "llm": {
                            "prompt": json.dumps(reflection_input, ensure_ascii=True),
                            "completion": reflection_text,
                        },
                    }
                )

                attempt += 1
                retry_events.append({"step_id": step.step_id, "attempt": attempt, "error": last_error})
                await self._sleep(self._backoff_seconds(classification, attempt))

    async def _reflect(self, payload: dict[str, Any]) -> str:
        try:
            response = await self._llm_provider.reason_step(json.dumps(payload, ensure_ascii=True))
            return response.text
        except Exception as exc:  # pragma: no cover - best effort reflection fallback
            return f"Reflection unavailable: {exc}"

    @staticmethod
    def _classify_error(kind: str, exc: Exception) -> str:
        message = str(exc).lower()
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return "transient"
        if "guardrail" in message:
            return "guardrail"
        if kind == "llm_reasoning" and ("rate limit" in message or "content filter" in message):
            return "llm"
        if isinstance(exc, ValueError) or "invalid" in message or "sql" in message:
            return "validation"
        return "unknown"

    @staticmethod
    def _backoff_seconds(classification: str, attempt: int) -> float:
        if classification == "transient":
            return {2: 0.0, 3: 0.0}.get(attempt, 0.0)
        if classification == "llm":
            return 0.0
        return 0.0
