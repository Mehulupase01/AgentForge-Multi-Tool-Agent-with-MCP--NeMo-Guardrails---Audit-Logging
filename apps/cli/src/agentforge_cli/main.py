from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from typing import Any

import click
import httpx


def parse_sse_lines(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    current_event: str | None = None
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip("\n")
        if not line:
            if current_event is not None:
                payload = "\n".join(data_lines) if data_lines else "{}"
                yield {"event": current_event, "data": json.loads(payload)}
            current_event = None
            data_lines = []
            continue

        if line.startswith("event: "):
            current_event = line.split(": ", 1)[1]
        elif line.startswith("data: "):
            data_lines.append(line.split(": ", 1)[1])

    if current_event is not None:
        payload = "\n".join(data_lines) if data_lines else "{}"
        yield {"event": current_event, "data": json.loads(payload)}


class AgentForgeAPI:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=os.getenv("AGENTFORGE_API_URL", "http://localhost:8000").rstrip("/"),
            headers={"X-API-Key": os.getenv("AGENTFORGE_API_KEY", "dev-key")},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def create_session(self) -> dict[str, Any]:
        return self._request("POST", "/api/v1/sessions", json={"metadata": {}})

    def create_task(self, session_id: str, prompt: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/sessions/{session_id}/tasks", json={"user_prompt": prompt})

    def stream_task(self, task_id: str) -> Iterator[dict[str, Any]]:
        with self._client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as response:
            response.raise_for_status()
            try:
                yield from parse_sse_lines(response.iter_lines())
            except httpx.RemoteProtocolError:
                return

    def list_approvals(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/approvals", params={"decision": "pending", "per_page": 50})

    def approve(self, approval_id: str, rationale: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approved", "rationale": rationale},
        )

    def verify_audit(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/audit/integrity")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = response.text
            try:
                payload = response.json()
                if isinstance(payload.get("error"), dict):
                    message = payload["error"].get("message", message)
            except ValueError:
                pass
            raise click.ClickException(message) from exc
        return response.json()


@click.group()
def main() -> None:
    """AgentForge CLI."""


@main.group()
def session() -> None:
    """Session operations."""


@session.command("new")
def session_new() -> None:
    api = AgentForgeAPI()
    try:
        session_payload = api.create_session()
        click.echo(f"session_id={session_payload['id']} status={session_payload['status']}")
    finally:
        api.close()


@main.group()
def task() -> None:
    """Task operations."""


@task.command("run")
@click.argument("prompt")
@click.option("--session-id", default=None, help="Reuse an existing session instead of creating a new one.")
def task_run(prompt: str, session_id: str | None) -> None:
    api = AgentForgeAPI()
    try:
        if session_id is None:
            session_payload = api.create_session()
            session_id = session_payload["id"]
            click.echo(f"session_id={session_id}")

        task_payload = api.create_task(session_id, prompt)
        task_id = task_payload["id"]
        click.echo(f"task_id={task_id} status={task_payload['status']}")

        final_response: str | None = None
        final_error: str | None = None
        for event in api.stream_task(task_id):
            data = event["data"]
            click.echo(f"event={event['event']} data={json.dumps(data, ensure_ascii=True)}")
            if event["event"] == "task_completed":
                final_response = data.get("final_response")
            elif event["event"] in {"task_failed", "task_rejected"}:
                final_error = data.get("error")

        if final_error:
            raise click.ClickException(final_error)
        click.echo(f"summary=completed final_response={json.dumps(final_response, ensure_ascii=True)}")
    finally:
        api.close()


@main.group()
def approval() -> None:
    """Approval operations."""


@approval.command("list")
def approval_list() -> None:
    api = AgentForgeAPI()
    try:
        payload = api.list_approvals()
        for item in payload["data"]:
            click.echo(
                f"id={item['id']} task_id={item['task_id']} risk={item['risk_level']} "
                f"decision={item['decision']} summary={json.dumps(item['action_summary'], ensure_ascii=True)}"
            )
    finally:
        api.close()


@approval.command("approve")
@click.argument("approval_id")
@click.option("--rationale", default=None, help="Optional rationale for the approval decision.")
def approval_approve(approval_id: str, rationale: str | None) -> None:
    api = AgentForgeAPI()
    try:
        payload = api.approve(approval_id, rationale=rationale)
        click.echo(f"id={payload['id']} decision={payload['decision']}")
    finally:
        api.close()


@main.group()
def audit() -> None:
    """Audit operations."""


@audit.command("verify")
def audit_verify() -> None:
    api = AgentForgeAPI()
    try:
        payload = api.verify_audit()
        click.echo(
            f"verified={str(payload['verified']).lower()} events_checked={payload['events_checked']} "
            f"first_broken_sequence={payload.get('first_broken_sequence')}"
        )
        if not payload["verified"]:
            raise SystemExit(1)
    finally:
        api.close()


if __name__ == "__main__":
    main()
