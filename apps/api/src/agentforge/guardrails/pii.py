from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider


SUPPORTED_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "IBAN_CODE",
    "CREDIT_CARD",
    "PERSON",
    "IP_ADDRESS",
    "IN_AADHAAR",
    "EU_PASSPORT",
]

_ANALYZER: AnalyzerEngine | None = None


@dataclass(slots=True)
class RedactionEntity:
    entity_type: str
    start: int
    end: int
    score: float
    replacement: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RedactionResult:
    text: str
    entities: list[RedactionEntity]

    @property
    def redacted(self) -> bool:
        return bool(self.entities)

    def to_rails_json(self) -> dict[str, Any]:
        return {
            "redacted": self.redacted,
            "entities": [entity.to_dict() for entity in self.entities],
        }


def _build_analyzer() -> AnalyzerEngine:
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    nlp_engine = provider.create_engine()

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers(nlp_engine=nlp_engine)
    registry.add_recognizer(
        PatternRecognizer(
            supported_entity="IN_AADHAAR",
            patterns=[Pattern(name="aadhaar", regex=r"\b\d{4}\s?\d{4}\s?\d{4}\b", score=0.8)],
        ),
    )
    registry.add_recognizer(
        PatternRecognizer(
            supported_entity="US_SSN",
            patterns=[Pattern(name="us_ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.9)],
        ),
    )
    registry.add_recognizer(
        PatternRecognizer(
            supported_entity="EU_PASSPORT",
            patterns=[Pattern(name="eu_passport", regex=r"\b[A-Z]{2}\d{6,8}\b", score=0.55)],
        ),
    )
    return AnalyzerEngine(registry=registry, nlp_engine=nlp_engine, supported_languages=["en"])


class PIIRedactor:
    def __init__(self) -> None:
        global _ANALYZER
        if _ANALYZER is None:
            _ANALYZER = _build_analyzer()
        self._analyzer = _ANALYZER

    def redact(self, text: str) -> RedactionResult:
        findings = self._analyzer.analyze(text=text, language="en", entities=SUPPORTED_ENTITIES)
        entities: list[RedactionEntity] = []
        for finding in findings:
            replacement = f"<{finding.entity_type}>"
            entities.append(
                RedactionEntity(
                    entity_type=finding.entity_type,
                    start=finding.start,
                    end=finding.end,
                    score=float(finding.score),
                    replacement=replacement,
                ),
            )

        if not findings:
            return RedactionResult(text=text, entities=[])

        entities.sort(key=lambda entity: entity.start)
        redacted_text = text
        for entity in reversed(entities):
            redacted_text = redacted_text[: entity.start] + entity.replacement + redacted_text[entity.end :]
        return RedactionResult(text=redacted_text, entities=entities)
