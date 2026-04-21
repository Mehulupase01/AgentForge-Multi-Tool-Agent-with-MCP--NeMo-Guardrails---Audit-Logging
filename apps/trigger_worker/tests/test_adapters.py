from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from trigger_worker.adapters.generic_http import verify_signature
from trigger_worker.adapters.github import event_name_from_payload, issue_opened_context


FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "triggers" / "github_issue_opened.json"


def test_generic_hmac_verify_pass_fail() -> None:
    body = b'{"hello":"world"}'
    secret = "topsecret"
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, signature) is True
    assert verify_signature(secret, body, "bad-signature") is False


def test_github_payload_parsing() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    headers = {"x-github-event": "issues"}
    assert event_name_from_payload(headers, payload) == "issues.opened"
    context = issue_opened_context(payload)
    assert context["issue"]["title"] == "Null ptr"
    assert context["repository"]["full_name"] == "acme/agentforge"
