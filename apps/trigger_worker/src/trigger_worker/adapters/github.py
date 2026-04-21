from __future__ import annotations


def event_name_from_payload(headers: dict[str, str], payload: dict) -> str:
    event = headers.get("x-github-event", "")
    action = str(payload.get("action", "")).strip()
    return f"{event}.{action}" if action else event


def issue_opened_context(payload: dict) -> dict:
    issue = payload.get("issue", {}) or {}
    repository = payload.get("repository", {}) or {}
    return {
        "issue": {
            "title": issue.get("title", ""),
            "body": issue.get("body", ""),
        },
        "repository": {
            "full_name": repository.get("full_name", ""),
        },
    }
