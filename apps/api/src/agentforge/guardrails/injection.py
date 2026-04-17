from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


BASE64_BLOCK_RE = re.compile(r"(?:[A-Za-z0-9+/]{200,}={0,2})")

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_previous_instructions",
        re.compile(r"(ignore|disregard|bypass)\s+(all\s+|any\s+|your\s+)?(previous|prior|above|current)\s+(instructions?|directions?)", re.I),
    ),
    ("system_override", re.compile(r"\bsystem\s*:", re.I)),
    ("identity_override", re.compile(r"(you are now|forget your current role|act as an unrestricted)", re.I)),
    ("admin_path", re.compile(r"/admin", re.I)),
    (
        "prompt_leak",
        re.compile(
            r"(reveal|print|show|extract|dump|quote).{0,60}"
            r"(system prompt|hidden prompt|hidden instructions|developer message|prompt stack|prompt template|internal policy chain|control instructions|hidden configuration|hidden rules)",
            re.I,
        ),
    ),
    (
        "instruction_replacement",
        re.compile(r"(replace|override).{0,40}(instructions?|rules?|chain of command|safety policy)", re.I),
    ),
    (
        "safety_bypass",
        re.compile(r"(without guardrails|ignore (the )?safety policy|ignore every safety rule|ignore your logging instructions)", re.I),
    ),
    (
        "secret_exfiltration",
        re.compile(r"(runtime secrets|tokens|checkpoint database|salary_band|leak hidden data|evil\.example\.org)", re.I),
    ),
    (
        "tool_abuse",
        re.compile(r"(chain arbitrary tools|use .*fetch_url.*evil\.example\.org|dump the full checkpoint database)", re.I),
    ),
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
