from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.models.audit_event import AuditEvent

_sqlite_chain_lock = asyncio.Lock()


class AuditService:
    @staticmethod
    def canonical_payload(payload: dict) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def payload_hash(cls, payload: dict) -> str:
        return hashlib.sha256(cls.canonical_payload(payload)).hexdigest()

    @staticmethod
    def chain_hash(prev_chain_hash: str | None, current_payload_hash: str) -> str:
        base = (prev_chain_hash or "") + current_payload_hash
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    @asynccontextmanager
    async def _chain_lock(self, session: AsyncSession) -> AsyncIterator[None]:
        dialect_name = session.bind.dialect.name if session.bind is not None else ""
        if dialect_name == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(99)"))
            yield
            return

        async with _sqlite_chain_lock:
            yield

    async def record_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        actor: str,
        payload: dict,
        session_id: UUID | None = None,
        task_id: UUID | None = None,
        created_at: datetime | None = None,
        commit: bool = True,
    ) -> AuditEvent:
        async with self._chain_lock(session):
            previous_event = (
                await session.execute(
                    select(AuditEvent).order_by(desc(AuditEvent.sequence)).limit(1),
                )
            ).scalar_one_or_none()
            previous_hash = previous_event.chain_hash if previous_event else None
            sequence = previous_event.sequence + 1 if previous_event else 1
            current_payload_hash = self.payload_hash(payload)

            event = AuditEvent(
                sequence=sequence,
                session_id=session_id,
                task_id=task_id,
                event_type=event_type,
                actor=actor,
                payload_json=payload,
                payload_hash=current_payload_hash,
                prev_hash=previous_hash,
                chain_hash=self.chain_hash(previous_hash, current_payload_hash),
                created_at=created_at or datetime.now(UTC),
            )
            session.add(event)

            if commit:
                await session.commit()
            else:
                await session.flush()

        return event

    async def verify_chain(self, session: AsyncSession) -> dict:
        events = list(
            (
                await session.execute(
                    select(AuditEvent).order_by(AuditEvent.sequence.asc()),
                )
            ).scalars()
        )
        previous_chain_hash: str | None = None

        for event in events:
            expected_payload_hash = self.payload_hash(event.payload_json)
            if event.payload_hash != expected_payload_hash:
                return {
                    "verified": False,
                    "events_checked": len(events),
                    "first_broken_sequence": event.sequence,
                    "expected_chain_hash": self.chain_hash(previous_chain_hash, expected_payload_hash),
                    "actual_chain_hash": event.chain_hash,
                }

            if event.prev_hash != previous_chain_hash:
                return {
                    "verified": False,
                    "events_checked": len(events),
                    "first_broken_sequence": event.sequence,
                    "expected_chain_hash": previous_chain_hash,
                    "actual_chain_hash": event.prev_hash,
                }

            expected_chain_hash = self.chain_hash(previous_chain_hash, event.payload_hash)
            if event.chain_hash != expected_chain_hash:
                return {
                    "verified": False,
                    "events_checked": len(events),
                    "first_broken_sequence": event.sequence,
                    "expected_chain_hash": expected_chain_hash,
                    "actual_chain_hash": event.chain_hash,
                }

            previous_chain_hash = event.chain_hash

        return {
            "verified": True,
            "events_checked": len(events),
            "first_broken_sequence": None,
            "expected_chain_hash": None,
            "actual_chain_hash": None,
        }

    async def record_guardrail_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        payload: dict,
        session_id: UUID | None = None,
        task_id: UUID | None = None,
        commit: bool = True,
    ) -> AuditEvent:
        return await self.record_event(
            session,
            event_type=event_type,
            actor="guardrail",
            payload=payload,
            session_id=session_id,
            task_id=task_id,
            commit=commit,
        )
