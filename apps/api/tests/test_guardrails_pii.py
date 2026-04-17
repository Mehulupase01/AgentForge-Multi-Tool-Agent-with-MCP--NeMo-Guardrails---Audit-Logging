from __future__ import annotations

from agentforge.guardrails.runner import GuardrailsRunner


def test_input_pii_redaction() -> None:
    runner = GuardrailsRunner()
    processed = runner.process_input("Email me at alice@example.com and call 555-123-4567.")
    assert processed.blocked is False
    assert "<EMAIL_ADDRESS>" in processed.text
    assert "<PHONE_NUMBER>" in processed.text


def test_output_pii_redaction() -> None:
    runner = GuardrailsRunner()
    processed = runner.process_output("The SSN is 123-45-6789.")
    assert "<US_SSN>" in processed.text


def test_input_rails_json_lists_entities() -> None:
    runner = GuardrailsRunner()
    processed = runner.process_input("Contact Bob at bob@example.com.")
    pii_info = processed.input_rails_json()["pii"]
    assert pii_info["redacted"] is True
    entity_types = {entity["entity_type"] for entity in pii_info["entities"]}
    assert "EMAIL_ADDRESS" in entity_types
