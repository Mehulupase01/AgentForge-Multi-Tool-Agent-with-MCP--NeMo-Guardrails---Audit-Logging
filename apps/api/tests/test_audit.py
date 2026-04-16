from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agentforge.services.audit_service import AuditService


async def test_audit_filters(client, db_session) -> None:
    first_session = (await client.post("/api/v1/sessions", json={})).json()
    second_session = (await client.post("/api/v1/sessions", json={})).json()

    service = AuditService()
    await service.record_event(
        db_session,
        event_type="task.created",
        actor="agent",
        payload={"label": "first"},
        session_id=UUID(first_session["id"]),
        created_at=datetime.now(UTC),
    )
    await service.record_event(
        db_session,
        event_type="task.failed",
        actor="agent",
        payload={"label": "second"},
        session_id=UUID(second_session["id"]),
        created_at=datetime.now(UTC),
    )

    paginated = await client.get("/api/v1/audit/events", params={"page": 1, "per_page": 2})
    assert paginated.status_code == 200
    assert paginated.json()["meta"]["total"] >= 4
    assert len(paginated.json()["data"]) == 2

    filtered = await client.get(
        "/api/v1/audit/events",
        params={"session_id": first_session["id"], "event_type": "task.created"},
    )
    assert filtered.status_code == 200
    filtered_data = filtered.json()["data"]
    assert len(filtered_data) == 1
    assert filtered_data[0]["event_type"] == "task.created"
    assert filtered_data[0]["session_id"] == first_session["id"]

    session_events = await client.get(f"/api/v1/audit/sessions/{first_session['id']}/events")
    assert session_events.status_code == 200
    assert [event["event_type"] for event in session_events.json()["data"]] == [
        "session.started",
        "task.created",
    ]
