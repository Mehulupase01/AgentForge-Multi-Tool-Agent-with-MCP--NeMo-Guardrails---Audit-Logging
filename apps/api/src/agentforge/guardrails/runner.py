from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentforge.guardrails.injection import InjectionDetector
from agentforge.guardrails.pii import PIIRedactor
from agentforge.guardrails.tool_allowlist import ToolAllowlist


ALLOWED_TOPIC_PATTERNS = (
    "ai",
    "ml",
    "machine learning",
    "transformer",
    "llm",
    "software",
    "code",
    "python",
    "api",
    "database",
    "employee",
    "project",
    "weather",
    "news",
    "github",
)

BLOCKED_TOPIC_PATTERNS = (
    "bomb",
    "weapon",
    "kill",
    "murder",
    "sexual",
    "porn",
    "steal",
    "fraud",
    "drugs",
    "credit card fraud",
    "hack bank",
)


class GuardrailBlocked(RuntimeError):
    def __init__(self, *, code: str, message: str, detail: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(slots=True)
class ProcessedInput:
    original_text: str
    text: str
    blocked: bool
    reason: str | None
    pii: dict[str, Any]
    injection: dict[str, Any]
    topic: dict[str, Any]

    def input_rails_json(self) -> dict[str, Any]:
        return {
            "pii": self.pii,
            "injection": self.injection,
            "topic": self.topic,
        }


@dataclass(slots=True)
class ProcessedOutput:
    original_text: str
    text: str
    blocked: bool
    reason: str | None
    pii: dict[str, Any]

    def output_rails_json(self) -> dict[str, Any]:
        return {"pii": self.pii}


@dataclass(slots=True)
class ToolCheckResult:
    allowed: bool
    reason: str | None
    detail: dict[str, Any]


class GuardrailsRunner:
    def __init__(
        self,
        *,
        pii_redactor: PIIRedactor | None = None,
        injection_detector: InjectionDetector | None = None,
        tool_allowlist: ToolAllowlist | None = None,
    ) -> None:
        self._pii_redactor = pii_redactor or PIIRedactor()
        self._injection_detector = injection_detector or InjectionDetector()
        self._tool_allowlist = tool_allowlist or ToolAllowlist()

    def process_input(self, prompt: str) -> ProcessedInput:
        pii_result = self._pii_redactor.redact(prompt)
        redacted_prompt = pii_result.text
        injection_result = self._injection_detector.scan(redacted_prompt)
        if injection_result.blocked:
            return ProcessedInput(
                original_text=prompt,
                text=redacted_prompt,
                blocked=True,
                reason="Prompt injection detected",
                pii=pii_result.to_rails_json(),
                injection=injection_result.to_dict(),
                topic={"allowed": False, "reason": "injection_blocked"},
            )

        topic_result = self._check_topic(redacted_prompt)
        return ProcessedInput(
            original_text=prompt,
            text=redacted_prompt,
            blocked=not topic_result["allowed"],
            reason=topic_result.get("reason"),
            pii=pii_result.to_rails_json(),
            injection=injection_result.to_dict(),
            topic=topic_result,
        )

    def process_output(self, text: str) -> ProcessedOutput:
        pii_result = self._pii_redactor.redact(text)
        return ProcessedOutput(
            original_text=text,
            text=pii_result.text,
            blocked=False,
            reason=None,
            pii=pii_result.to_rails_json(),
        )

    def check_tool(self, server: str, tool: str) -> ToolCheckResult:
        allowed = self._tool_allowlist.is_allowed(server, tool)
        if allowed:
            return ToolCheckResult(allowed=True, reason=None, detail={"server": server, "tool": tool})
        return ToolCheckResult(
            allowed=False,
            reason="Tool is not in the configured allowlist",
            detail={"server": server, "tool": tool},
        )

    @staticmethod
    def _check_topic(text: str) -> dict[str, Any]:
        lowered = text.lower()
        if any(pattern in lowered for pattern in BLOCKED_TOPIC_PATTERNS):
            return {"allowed": False, "reason": "Blocked topic"}
        if any(pattern in lowered for pattern in ALLOWED_TOPIC_PATTERNS):
            return {"allowed": True, "reason": None}
        if any(token in lowered for token in ("dating", "horoscope", "celebrity gossip", "relationship advice")):
            return {"allowed": False, "reason": "Topic outside the allowed scope"}
        return {"allowed": True, "reason": None}


_guardrails_runner: GuardrailsRunner | None = None


def get_guardrails_runner() -> GuardrailsRunner:
    global _guardrails_runner
    if _guardrails_runner is None:
        _guardrails_runner = GuardrailsRunner()
    return _guardrails_runner
