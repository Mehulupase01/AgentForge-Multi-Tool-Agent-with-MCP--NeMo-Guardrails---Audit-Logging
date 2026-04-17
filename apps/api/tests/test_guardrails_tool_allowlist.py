from __future__ import annotations

from pathlib import Path

import yaml

from agentforge.guardrails.runner import GuardrailsRunner
from agentforge.guardrails.tool_allowlist import ToolAllowlist


def write_allowlist(path: Path) -> Path:
    payload = {
        "allowlist": {
            "file_search": ["search_corpus", "read_document"],
            "web_fetch": ["weather_for"],
        }
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return path


def test_disallowed_tool_is_blocked(tmp_path: Path) -> None:
    runner = GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "allowlist.yml")))
    result = runner.check_tool("web_fetch", "hacker_news_top")
    assert result.allowed is False
    assert result.reason == "Tool is not in the configured allowlist"


def test_allowlisted_tool_passes(tmp_path: Path) -> None:
    runner = GuardrailsRunner(tool_allowlist=ToolAllowlist(write_allowlist(tmp_path / "allowlist.yml")))
    result = runner.check_tool("file_search", "search_corpus")
    assert result.allowed is True
