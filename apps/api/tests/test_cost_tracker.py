from __future__ import annotations

from datetime import UTC, datetime

import pytest
import tiktoken

from agentforge.models.agent_run import AgentRole
from agentforge.models.llm_call import LLMCall
from agentforge.models.session import Session, SessionStatus
from agentforge.models.task import Task, TaskStatus
from agentforge.services.cost_tracker import CostTracker


@pytest.mark.asyncio
async def test_cost_tracker_accuracy_within_5pct(session_factory) -> None:
    prompt = "Summarize the engineering headcount changes across product and platform."
    completion = "Engineering headcount grew in platform while product stayed flat."
    encoding = tiktoken.encoding_for_model("gpt-4o-mini")
    provider_prompt_tokens = len(encoding.encode(prompt))
    provider_completion_tokens = len(encoding.encode(completion))

    async with session_factory() as session:
        work_session = Session(
            user_id="cost-test",
            status=SessionStatus.ACTIVE,
            started_at=datetime.now(UTC),
            metadata_json={},
        )
        session.add(work_session)
        await session.flush()
        task = Task(
            session_id=work_session.id,
            user_prompt=prompt,
            status=TaskStatus.COMPLETED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            final_response=completion,
        )
        session.add(task)
        await session.flush()
        llm_call = LLMCall(
            provider="openai",
            model="gpt-4o-mini",
            prompt=prompt,
            completion=completion,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=12,
        )
        session.add(llm_call)
        await session.commit()

        tracker = CostTracker()
        record = await tracker.record(
            session,
            llm_call_id=llm_call.id,
            task_id=task.id,
            agent_role=AgentRole.ORCHESTRATOR,
        )
        await session.commit()

        assert abs(record.prompt_tokens - provider_prompt_tokens) / max(provider_prompt_tokens, 1) <= 0.05
        assert abs(record.completion_tokens - provider_completion_tokens) / max(provider_completion_tokens, 1) <= 0.05
        assert record.usd_cost > 0
