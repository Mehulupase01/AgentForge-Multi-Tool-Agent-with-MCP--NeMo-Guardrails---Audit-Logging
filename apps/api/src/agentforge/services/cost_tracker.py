from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import tiktoken
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.config import settings
from agentforge.models.agent_run import AgentRole
from agentforge.models.cost_record import CostRecord
from agentforge.models.llm_call import LLMCall
from agentforge.models.task_step import TaskStep
from agentforge.services.audit_service import AuditService


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_1k_usd: float
    output_per_1k_usd: float


class CostTracker:
    def __init__(self, *, audit_service: AuditService | None = None, pricing_path: Path | None = None) -> None:
        self._audit_service = audit_service or AuditService()
        self._pricing_path = pricing_path or settings.openai_prices_path_resolved

    async def record(
        self,
        session: AsyncSession,
        *,
        llm_call_id: UUID,
        task_id: UUID | None = None,
        agent_role: AgentRole | None = None,
        commit: bool = False,
    ) -> CostRecord:
        llm_call = await session.get(LLMCall, llm_call_id)
        if llm_call is None:
            raise RuntimeError(f"LLMCall {llm_call_id} not found for cost tracking.")

        existing = (
            await session.execute(select(CostRecord).where(CostRecord.llm_call_id == llm_call_id))
        ).scalars().first()
        resolved_task_id, resolved_role = await self._resolve_context(
            session,
            llm_call=llm_call,
            task_id=task_id,
            agent_role=agent_role,
        )
        prompt_tokens, completion_tokens = self._token_counts(llm_call)
        price = self._price_for_model(llm_call.model)
        usd_cost = ((prompt_tokens / 1000.0) * price.input_per_1k_usd) + (
            (completion_tokens / 1000.0) * price.output_per_1k_usd
        )

        record = existing or CostRecord(
            task_id=resolved_task_id,
            llm_call_id=llm_call.id,
            agent_role=resolved_role,
            provider=llm_call.provider,
            model=llm_call.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd_cost=usd_cost,
            recorded_at=datetime.now(UTC),
        )
        record.task_id = resolved_task_id
        record.agent_role = resolved_role
        record.provider = llm_call.provider
        record.model = llm_call.model
        record.prompt_tokens = prompt_tokens
        record.completion_tokens = completion_tokens
        record.usd_cost = usd_cost
        record.recorded_at = datetime.now(UTC)
        session.add(record)
        await session.flush()

        await self._audit_service.record_event(
            session,
            event_type="cost.recorded",
            actor="system",
            payload={
                "task_id": str(resolved_task_id),
                "llm_call_id": str(llm_call.id),
                "agent_role": resolved_role.value,
                "model": llm_call.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "usd_cost": round(usd_cost, 8),
            },
            task_id=resolved_task_id,
            commit=False,
        )
        if commit:
            await session.commit()
        return record

    async def _resolve_context(
        self,
        session: AsyncSession,
        *,
        llm_call: LLMCall,
        task_id: UUID | None,
        agent_role: AgentRole | None,
    ) -> tuple[UUID, AgentRole]:
        resolved_task_id = task_id
        resolved_role = agent_role
        if llm_call.task_step_id is not None:
            step = await session.get(TaskStep, llm_call.task_step_id)
            if step is not None:
                resolved_task_id = resolved_task_id or step.task_id
                resolved_role = resolved_role or step.agent_role
        if resolved_task_id is None:
            raise RuntimeError("CostTracker.record requires task_id when LLMCall is not linked to a task step.")
        return resolved_task_id, resolved_role or AgentRole.ORCHESTRATOR

    def _token_counts(self, llm_call: LLMCall) -> tuple[int, int]:
        prompt_tokens = llm_call.prompt_tokens
        completion_tokens = llm_call.completion_tokens
        if prompt_tokens is None:
            prompt_tokens = self._count_tokens(llm_call.prompt, llm_call.model)
        if completion_tokens is None:
            completion_tokens = self._count_tokens(llm_call.completion or "", llm_call.model)
        return prompt_tokens, completion_tokens

    @staticmethod
    @lru_cache(maxsize=64)
    def _encoding_for(model_name: str):
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str, model_name: str) -> int:
        if not text:
            return 0
        return len(self._encoding_for(model_name).encode(text))

    def _price_for_model(self, model_name: str) -> ModelPrice:
        pricing = self._load_pricing_table(self._pricing_path)
        model_entry = pricing["models"].get(model_name) or pricing["default"]
        return ModelPrice(
            input_per_1k_usd=float(model_entry["input_per_1k_usd"]),
            output_per_1k_usd=float(model_entry["output_per_1k_usd"]),
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _load_pricing_table(path: Path) -> dict[str, Any]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "models" not in payload or "default" not in payload:
            raise ValueError("Pricing file must define 'models' and 'default'.")
        return payload
