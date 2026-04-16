from __future__ import annotations

import asyncio

from sqlalchemy import text

from agentforge.services.audit_service import AuditService


async def test_audit_chain_integrity_clean(session_factory) -> None:
    service = AuditService()
    for idx in range(50):
        async with session_factory() as session:
            await service.record_event(
                session,
                event_type="audit.test",
                actor="tester",
                payload={"index": idx},
            )

    async with session_factory() as session:
        integrity = await service.verify_chain(session)

    assert integrity["verified"] is True
    assert integrity["events_checked"] == 50
    assert integrity["first_broken_sequence"] is None


async def test_audit_chain_detects_tampering(session_factory) -> None:
    service = AuditService()
    for idx in range(10):
        async with session_factory() as session:
            await service.record_event(
                session,
                event_type="audit.test",
                actor="tester",
                payload={"index": idx},
            )

    async with session_factory() as session:
        await session.execute(text("UPDATE audit_events SET payload_json = '{}' WHERE sequence = 5"))
        await session.commit()
        integrity = await service.verify_chain(session)

    assert integrity["verified"] is False
    assert integrity["first_broken_sequence"] == 5


async def test_audit_chain_detects_deletion(session_factory) -> None:
    service = AuditService()
    for idx in range(10):
        async with session_factory() as session:
            await service.record_event(
                session,
                event_type="audit.test",
                actor="tester",
                payload={"index": idx},
            )

    async with session_factory() as session:
        await session.execute(text("DELETE FROM audit_events WHERE sequence = 5"))
        await session.commit()
        integrity = await service.verify_chain(session)

    assert integrity["verified"] is False
    assert integrity["first_broken_sequence"] == 6


async def test_audit_concurrent_writes(session_factory) -> None:
    service = AuditService()

    async def record_one(index: int) -> int:
        async with session_factory() as session:
            event = await service.record_event(
                session,
                event_type="audit.concurrent",
                actor="tester",
                payload={"index": index},
            )
            return event.sequence

    sequences = await asyncio.gather(*[record_one(index) for index in range(100)])
    assert sorted(sequences) == list(range(1, 101))

    async with session_factory() as session:
        integrity = await service.verify_chain(session)

    assert integrity["verified"] is True
