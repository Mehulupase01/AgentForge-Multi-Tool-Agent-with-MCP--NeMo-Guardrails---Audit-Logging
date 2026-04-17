from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agentforge.config import settings


class ToolAllowlist:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or settings.mcp_tool_allowlist_path)
        self._loaded: dict[str, set[str]] | None = None

    def _load(self) -> dict[str, set[str]]:
        if self._loaded is not None:
            return self._loaded
        payload = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        allowlist = payload.get("allowlist", {})
        self._loaded = {
            server: {str(tool) for tool in (tools or [])}
            for server, tools in allowlist.items()
        }
        return self._loaded

    def is_allowed(self, server: str, tool: str) -> bool:
        return tool in self._load().get(server, set())

    def to_dict(self) -> dict[str, Any]:
        return {server: sorted(tools) for server, tools in self._load().items()}
