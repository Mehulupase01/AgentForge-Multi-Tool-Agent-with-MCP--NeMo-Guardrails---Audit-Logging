from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


BASE64_BLOCK_RE = re.compile(r"(?:[A-Za-z0-9+/]{200,}={0,2})")

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_previous_instructions", re.compile(r"ignore (all |any )?(previous|prior) instructions", re.I)),
    ("system_override", re.compile(r"\bsystem\s*:", re.I)),
    ("identity_override", re.compile(r"you are now", re.I)),
    ("admin_path", re.compile(r"/admin", re.I)),
    ("prompt_leak", re.compile(r"(reveal|print|show).{0,40}(system prompt|hidden prompt)", re.I)),
]


@dataclass(slots=True)
class InjectionScanResult:
    blocked: bool
    matched_patterns: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InjectionDetector:
    def scan(self, text: str) -> InjectionScanResult:
        matches = [name for name, pattern in PATTERNS if pattern.search(text)]
        if BASE64_BLOCK_RE.search(text):
            matches.append("base64_blob")
        return InjectionScanResult(blocked=bool(matches), matched_patterns=matches)
