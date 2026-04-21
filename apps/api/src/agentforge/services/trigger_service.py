from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.config import settings
from agentforge.models.session import Session, SessionStatus
from agentforge.models.task import Task, TaskStatus
from agentforge.models.trigger import Trigger, TriggerEvent, TriggerEventStatus, TriggerSource, TriggerStatus
from agentforge.services.audit_service import AuditService


def _canonical_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


@dataclass(slots=True)
class TriggerProcessResult:
    trigger_event: TriggerEvent
    accepted: bool
    task: Task | None


class TriggerService:
    def __init__(self, audit_service: AuditService | None = None) -> None:
        self._audit_service = audit_service or AuditService()

    async def create_trigger(
        self,
        session: AsyncSession,
        *,
        name: str,
        source: TriggerSource,
        config: dict[str, Any],
        prompt_template: str,
        secret: str | None,
        status: TriggerStatus,
    ) -> Trigger:
        trigger = Trigger(
            name=name,
            source=source,
            config_json=config,
            prompt_template=prompt_template,
            secret=secret,
            status=status,
        )
        session.add(trigger)
        await session.commit()
        await session.refresh(trigger)
        return trigger

    async def get_trigger(self, session: AsyncSession, trigger_id: UUID) -> Trigger | None:
        return await session.get(Trigger, trigger_id)

    async def list_triggers(self, session: AsyncSession) -> list[Trigger]:
        return list((await session.execute(select(Trigger).order_by(Trigger.created_at.asc()))).scalars())

    async def update_trigger(self, session: AsyncSession, trigger: Trigger, **changes: Any) -> Trigger:
        for field_name, value in changes.items():
            if value is not None:
                setattr(trigger, field_name, value)
        await session.commit()
        await session.refresh(trigger)
        return trigger

    async def delete_trigger(self, session: AsyncSession, trigger: Trigger) -> None:
        await session.delete(trigger)
        await session.commit()

    async def list_events(self, session: AsyncSession, trigger_id: UUID) -> list[TriggerEvent]:
        return list(
            (
                await session.execute(
                    select(TriggerEvent)
                    .where(TriggerEvent.trigger_id == trigger_id)
                    .order_by(TriggerEvent.received_at.asc())
                )
            ).scalars()
        )

    async def process_webhook(
        self,
        session: AsyncSession,
        *,
        source: TriggerSource,
        headers: dict[str, str],
        raw_body: bytes,
        payload: dict[str, Any],
    ) -> TriggerProcessResult:
        trigger = await self._match_trigger(session, source=source, headers=headers, payload=payload)
        if trigger is None:
            raise LookupError("No matching trigger registered for this webhook.")

        normalized_headers = _canonical_headers(headers)
        event = TriggerEvent(
            trigger_id=trigger.id,
            source_headers_json=normalized_headers,
            payload_json=payload,
            signature_valid=False,
            status=TriggerEventStatus.RECEIVED,
            received_at=datetime.now(UTC),
        )
        session.add(event)
        await session.flush()

        await self._audit_service.record_event(
            session,
            event_type="trigger.received",
            actor=source.value,
            payload={"trigger_id": str(trigger.id), "trigger_event_id": str(event.id)},
            commit=False,
        )

        signature_valid = self._verify_signature(trigger, source=source, headers=normalized_headers, raw_body=raw_body)
        event.signature_valid = signature_valid
        if not signature_valid:
            event.status = TriggerEventStatus.REJECTED
            event.rejection_reason = "invalid_signature"
            event.processed_at = datetime.now(UTC)
            await self._audit_service.record_event(
                session,
                event_type="trigger.rejected",
                actor=source.value,
                payload={
                    "trigger_id": str(trigger.id),
                    "trigger_event_id": str(event.id),
                    "reason": event.rejection_reason,
                },
                commit=False,
            )
            await session.commit()
            return TriggerProcessResult(trigger_event=event, accepted=False, task=None)

        if trigger.status == TriggerStatus.DISABLED:
            event.status = TriggerEventStatus.REJECTED
            event.rejection_reason = "trigger_disabled"
            event.processed_at = datetime.now(UTC)
            await self._audit_service.record_event(
                session,
                event_type="trigger.rejected",
                actor=source.value,
                payload={
                    "trigger_id": str(trigger.id),
                    "trigger_event_id": str(event.id),
                    "reason": event.rejection_reason,
                },
                commit=False,
            )
            await session.commit()
            return TriggerProcessResult(trigger_event=event, accepted=False, task=None)

        task = await self._create_task_from_trigger_event(session, trigger=trigger, event=event, payload=payload)
        return TriggerProcessResult(trigger_event=event, accepted=True, task=task)

    async def fire_internal_schedule(
        self,
        session: AsyncSession,
        *,
        trigger_id: UUID,
    ) -> TriggerProcessResult:
        trigger = await session.get(Trigger, trigger_id)
        if trigger is None:
            raise LookupError("Trigger not found.")

        event = TriggerEvent(
            trigger_id=trigger.id,
            source_headers_json={"x-internal-source": "trigger_worker"},
            payload_json={"trigger_id": str(trigger.id), "source": "schedule"},
            signature_valid=True,
            status=TriggerEventStatus.RECEIVED,
            received_at=datetime.now(UTC),
        )
        session.add(event)
        await session.flush()
        await self._audit_service.record_event(
            session,
            event_type="trigger.received",
            actor=TriggerSource.SCHEDULE.value,
            payload={"trigger_id": str(trigger.id), "trigger_event_id": str(event.id)},
            commit=False,
        )

        if trigger.status == TriggerStatus.DISABLED:
            event.status = TriggerEventStatus.REJECTED
            event.rejection_reason = "trigger_disabled"
            event.processed_at = datetime.now(UTC)
            await self._audit_service.record_event(
                session,
                event_type="trigger.rejected",
                actor=TriggerSource.SCHEDULE.value,
                payload={
                    "trigger_id": str(trigger.id),
                    "trigger_event_id": str(event.id),
                    "reason": event.rejection_reason,
                },
                commit=False,
            )
            await session.commit()
            return TriggerProcessResult(trigger_event=event, accepted=False, task=None)

        task = await self._create_task_from_trigger_event(session, trigger=trigger, event=event, payload=event.payload_json)
        return TriggerProcessResult(trigger_event=event, accepted=True, task=task)

    async def _create_task_from_trigger_event(
        self,
        session: AsyncSession,
        *,
        trigger: Trigger,
        event: TriggerEvent,
        payload: dict[str, Any],
    ) -> Task:
        prompt = self.render_prompt(trigger.prompt_template, payload)
        system_session = Session(
            user_id=f"trigger:{trigger.source.value}",
            status=SessionStatus.ACTIVE,
            started_at=datetime.now(UTC),
            metadata_json={"trigger_id": str(trigger.id), "source": trigger.source.value},
        )
        session.add(system_session)
        await session.flush()

        task = Task(
            session_id=system_session.id,
            trigger_event_id=event.id,
            user_prompt=prompt,
            status=TaskStatus.PLANNING,
        )
        session.add(task)
        await session.flush()

        trigger.last_fired_at = datetime.now(UTC)
        event.resulting_task_id = task.id
        event.status = TriggerEventStatus.ACCEPTED
        event.processed_at = datetime.now(UTC)

        await self._audit_service.record_event(
            session,
            event_type="trigger.fired",
            actor=trigger.source.value,
            payload={
                "trigger_id": str(trigger.id),
                "trigger_event_id": str(event.id),
                "task_id": str(task.id),
            },
            session_id=system_session.id,
            task_id=task.id,
            commit=False,
        )
        await session.commit()
        await session.refresh(task)
        return task

    async def _match_trigger(
        self,
        session: AsyncSession,
        *,
        source: TriggerSource,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> Trigger | None:
        triggers = list(
            (
                await session.execute(
                    select(Trigger)
                    .where(Trigger.source == source)
                    .order_by(Trigger.created_at.asc())
                )
            ).scalars()
        )
        if source == TriggerSource.GITHUB_WEBHOOK:
            event_name = headers.get("x-github-event", "")
            action = str(payload.get("action", "")).strip()
            combined = f"{event_name}.{action}" if action else event_name
            for trigger in triggers:
                expected = str(trigger.config_json.get("event", "")).strip()
                if expected == combined:
                    return trigger
        return triggers[0] if triggers else None

    @staticmethod
    def render_prompt(template_text: str, payload: dict[str, Any]) -> str:
        template = Template(template_text)
        return template.render(**payload).strip()

    @staticmethod
    def _verify_signature(
        trigger: Trigger,
        *,
        source: TriggerSource,
        headers: dict[str, str],
        raw_body: bytes,
    ) -> bool:
        if source == TriggerSource.GITHUB_WEBHOOK:
            default_secret = settings.github_webhook_secret or ""
        else:
            default_secret = settings.generic_webhook_secret or ""
        secret = trigger.secret or default_secret
        if not secret:
            return False
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if source == TriggerSource.GITHUB_WEBHOOK:
            expected = f"sha256={digest}"
            actual = headers.get("x-hub-signature-256", "")
            return hmac.compare_digest(actual, expected)
        actual = headers.get("x-signature-256", "")
        return hmac.compare_digest(actual, digest)


_trigger_service: TriggerService | None = None


def get_trigger_service() -> TriggerService:
    global _trigger_service
    if _trigger_service is None:
        _trigger_service = TriggerService()
    return _trigger_service
