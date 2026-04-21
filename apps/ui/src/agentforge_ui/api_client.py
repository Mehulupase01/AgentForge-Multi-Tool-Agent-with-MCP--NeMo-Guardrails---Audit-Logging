from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from typing import Any

import httpx


def parse_sse_lines(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    current_event: str | None = None
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip("\n")
        if not line:
            if current_event is not None:
                payload = "\n".join(data_lines) if data_lines else "{}"
                yield {
                    "event": current_event,
                    "data": json.loads(payload),
                }
            current_event = None
            data_lines = []
            continue

        if line.startswith("event: "):
            current_event = line.split(": ", 1)[1]
        elif line.startswith("data: "):
            data_lines.append(line.split(": ", 1)[1])

    if current_event is not None:
        payload = "\n".join(data_lines) if data_lines else "{}"
        yield {
            "event": current_event,
            "data": json.loads(payload),
        }


class AgentForgeClient:
    def __init__(self, *, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    @classmethod
    def from_env(cls) -> "AgentForgeClient":
        return cls(
            base_url=os.getenv("AGENTFORGE_API_URL", "http://localhost:8000"),
            api_key=os.getenv("AGENTFORGE_API_KEY", "dev-key"),
        )

    def close(self) -> None:
        self._client.close()

    def get_readiness(self) -> dict[str, Any]:
        response = self._client.get("/api/v1/health/readiness")
        response.raise_for_status()
        return response.json()

    def list_sessions(self, *, page: int = 1, per_page: int = 10) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/sessions", params={"page": page, "per_page": per_page})

    def create_session(self, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request_json("POST", "/api/v1/sessions", json={"metadata": metadata or {}})

    def create_task(self, session_id: str, *, user_prompt: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/api/v1/sessions/{session_id}/tasks",
            json={"user_prompt": user_prompt},
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/v1/tasks/{task_id}")

    def stream_task(self, task_id: str) -> Iterator[dict[str, Any]]:
        with self._client.stream("GET", f"/api/v1/tasks/{task_id}/stream") as response:
            response.raise_for_status()
            try:
                yield from parse_sse_lines(response.iter_lines())
            except httpx.RemoteProtocolError:
                return

    def list_approvals(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        decision: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if decision:
            params["decision"] = decision
        if task_id:
            params["task_id"] = task_id
        return self._request_json("GET", "/api/v1/approvals", params=params)

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/v1/approvals/{approval_id}")

    def decide_approval(self, approval_id: str, *, decision: str, rationale: str | None = None) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": decision, "rationale": rationale},
        )

    def list_audit_events(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        event_types: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if event_types:
            params["event_type"] = event_types
        if session_id:
            params["session_id"] = session_id
        return self._request_json("GET", "/api/v1/audit/events", params=params)

    def verify_audit(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/audit/integrity")

    def list_redteam_runs(self, *, page: int = 1, per_page: int = 10) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/redteam/runs", params={"page": page, "per_page": per_page})

    def get_redteam_run(self, run_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/v1/redteam/runs/{run_id}")

    def list_redteam_results(
        self,
        run_id: str,
        *,
        page: int = 1,
        per_page: int = 200,
        category: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if category:
            params["category"] = category
        return self._request_json("GET", f"/api/v1/redteam/runs/{run_id}/results", params=params)

    def start_redteam_run(self, *, scenario_ids: list[str] | None = None) -> dict[str, Any]:
        return self._request_json("POST", "/api/v1/redteam/run", json={"scenario_ids": scenario_ids})

    def get_task_cost(self, task_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/v1/observability/tasks/{task_id}/cost")

    def get_task_confidence(self, task_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/v1/observability/tasks/{task_id}/confidence")

    def get_observability_summary(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/observability/summary")

    def get_agent_handoffs(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/observability/agent_handoffs")

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(self._extract_error_message(exc.response)) from exc
        return response.json()

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message", response.text)
        return response.text
