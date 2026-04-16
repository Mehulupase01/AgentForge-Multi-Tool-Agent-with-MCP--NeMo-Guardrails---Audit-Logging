from __future__ import annotations

from sqlalchemy import func, select

from agentforge.models.audit_event import AuditEvent


async def test_session_lifecycle(client, db_session) -> None:
    create_response = await client.post("/api/v1/sessions", json={"metadata": {"source": "test"}})

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["user_id"] == "demo_user"
    assert created["status"] == "active"
    assert created["metadata"] == {"source": "test"}

    session_id = created["id"]

    fetch_response = await client.get(f"/api/v1/sessions/{session_id}")
    assert fetch_response.status_code == 200
    fetched = fetch_response.json()
    assert fetched["task_count"] == 0
    assert fetched["tool_call_count"] == 0
    assert fetched["approval_count"] == 0

    end_response = await client.post(f"/api/v1/sessions/{session_id}/end")
    assert end_response.status_code == 200
    ended = end_response.json()
    assert ended["status"] == "completed"
    assert ended["ended_at"] is not None

    repeat_end_response = await client.post(f"/api/v1/sessions/{session_id}/end")
    assert repeat_end_response.status_code == 409
    assert repeat_end_response.json()["error"]["code"] == "CONFLICT"

    event_count = int((await db_session.execute(select(func.count()).select_from(AuditEvent))).scalar_one())
    assert event_count == 2
