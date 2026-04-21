from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "fixtures" / "corpus"

TOPICS = [
    "Transformer Architectures in Practice",
    "Retrieval Augmented Generation Design",
    "Vector Embeddings and Semantic Search",
    "Prompt Injection Defense Patterns",
    "Human in the Loop Approval Systems",
    "Evaluation Metrics for Agentic Systems",
    "Tool Calling Reliability in LLM Agents",
    "Multi Agent Coordination Tradeoffs",
    "Fine Tuning Versus In Context Learning",
    "Synthetic Data for Enterprise AI",
    "Knowledge Graphs for AI Assistants",
    "Observability for LLM Applications",
    "Model Context Protocol Fundamentals",
    "Chain of Thought Risk Management",
    "Latency Optimization for AI APIs",
    "Guardrails for Sensitive Data",
    "Red Teaming Autonomous Workflows",
    "Enterprise Search Architecture",
    "Long Context Window Engineering",
    "Caching Strategies for AI Systems",
    "Model Routing in Production",
    "Hybrid Search and Ranking",
    "Responsible AI Governance",
    "Feature Stores for ML Platforms",
    "Data Quality Monitoring for ML",
    "Drift Detection in Production Models",
    "A B Testing for LLM Features",
    "Knowledge Distillation Concepts",
    "Reinforcement Learning from Feedback",
    "Open Source Foundation Models",
    "Agent Memory Design Patterns",
    "Graph Based Task Planning",
    "Incident Response for AI Services",
    "Security Review for MCP Tools",
    "Structured Output Validation",
    "Benchmarking Text Generation Systems",
    "Dataset Versioning for ML Teams",
    "Cost Controls for Inference Platforms",
    "Access Control in AI Products",
    "Privacy Preserving Data Pipelines",
    "MLOps Pipelines for Foundation Models",
    "Streaming Interfaces for Agent Systems",
    "SQLite as a Lightweight Tool Backend",
    "FastAPI Patterns for AI Control Planes",
    "Grounded Summarization Techniques",
    "Hallucination Detection Strategies",
    "Search Index Freshness Management",
    "LLM Safety Policy Enforcement",
    "Enterprise Chat UX Design",
    "Tool Allowlists and Least Privilege",
    "Resilient Background Job Processing",
    "Audit Trails for AI Compliance",
    "Continuous Verification for Agents",
]

KNOWLEDGE_DOCS: dict[str, str] = {
    "hr-policy.md": (
        "---\n"
        "title: HR Policy Guardrails\n"
        "topic: workforce policy\n"
        "summary: Internal HR guidance for safe workforce reporting and protected field handling.\n"
        "---\n\n"
        "# HR Policy Guardrails\n\n"
        "Workforce analytics should prefer bounded staffing and assignment views over broad compensation extracts. "
        "Protected fields such as salary bands require an approval checkpoint before they are exposed in reports or "
        "operator workflows.\n"
    ),
    "project-taxonomy.md": (
        "---\n"
        "title: Project Taxonomy\n"
        "topic: taxonomy\n"
        "summary: Reference taxonomy for research, engineering, and workforce tasks in AgentForge.\n"
        "---\n\n"
        "# Project Taxonomy\n\n"
        "AgentForge groups work into workforce analytics, corpus research, repository health, and customer "
        "communication so that skills can keep tools and policies tightly scoped.\n"
    ),
    "tone-of-voice.md": (
        "---\n"
        "title: Tone Of Voice\n"
        "topic: communication\n"
        "summary: Communication guidance for summaries and outward-facing responses.\n"
        "---\n\n"
        "# Tone Of Voice\n\n"
        "Customer and operator messaging should be calm, precise, and explicit about what was found, what remains "
        "uncertain, and what safe next step is recommended.\n"
    ),
    "repo-health-guide.md": (
        "---\n"
        "title: Repository Health Guide\n"
        "topic: repository health\n"
        "summary: Practical guidance for assessing repository health through safe GitHub reads.\n"
        "---\n\n"
        "# Repository Health Guide\n\n"
        "Repository health reviews should stay read-only and emphasize signals like documentation quality, backlog "
        "shape, and maintenance cadence instead of guessing about hidden project state.\n"
    ),
}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def build_document(title: str, ordinal: int) -> str:
    topic_key = slugify(title).replace("-", " ")
    paragraphs: list[str] = []
    paragraph_templates = [
        (
            "{title} matters because enterprise AI programs are judged on reliability, traceability, "
            "and operational fit, not only on raw model quality. Teams adopting {topic} need clear "
            "interfaces, reproducible procedures, measurable outcomes, and service boundaries that can "
            "survive compliance review, handoffs, and changing business priorities."
        ),
        (
            "A practical rollout starts with deterministic inputs, explicit schemas, and logged decisions. "
            "When {topic} is framed as a system concern instead of a model trick, engineers can attach "
            "tests, alerts, fallback behavior, and human checkpoints. That approach reduces hidden state, "
            "shrinks recovery time, and makes every incident easier to diagnose."
        ),
        (
            "Architecture choices around {topic} should balance speed and control. Small teams often begin "
            "with simple components, but production systems still need contracts for storage, retrieval, "
            "security, and auditability. Clear component ownership keeps later optimization work from "
            "turning into risky rewrites that cut across the whole platform."
        ),
        (
            "Operational maturity also depends on measurement. Useful signals include latency percentiles, "
            "throughput, failure rates, reviewer burden, policy violations, and user-visible correctness. "
            "By connecting those signals back to {topic}, teams learn whether a new tactic improves the "
            "system or simply shifts risk to another layer."
        ),
        (
            "Good documentation turns {topic} from tribal knowledge into repeatable practice. Runbooks, "
            "fixtures, and acceptance criteria help new contributors reason about intent before editing "
            "code. That discipline is especially valuable in AI stacks, where model behavior changes faster "
            "than surrounding application assumptions."
        ),
        (
            "The most durable strategy is to treat {topic} as an evolving capability with strong defaults, "
            "bounded interfaces, and regular verification. Teams that revisit assumptions, record tradeoffs, "
            "and keep human operators in the loop where needed usually outperform teams that optimize only "
            "for demo speed. The result is a calmer, more governable platform."
        ),
    ]

    for template in paragraph_templates:
        paragraphs.append(template.format(title=title, topic=topic_key))

    summary = (
        f"Deterministic reference note {ordinal:02d} covering {title.lower()} "
        "for the AgentForge fixture corpus."
    )
    body = "\n\n".join(paragraphs)
    return (
        "---\n"
        f"title: {title}\n"
        f"topic: {topic_key}\n"
        f"summary: {summary}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def write_readme(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "This directory holds 50+ markdown files about AI/ML topics for the file_search MCP. "
        "Generated by `apps/api/src/agentforge/tools/generate_corpus.py`.\n",
        encoding="utf-8",
    )


def generate_corpus(output_dir: Path | None = None) -> list[Path]:
    destination = output_dir or DEFAULT_OUTPUT_DIR
    destination.mkdir(parents=True, exist_ok=True)
    write_readme(destination)

    written: list[Path] = []
    for ordinal, title in enumerate(TOPICS, start=1):
        filename = f"{ordinal:02d}-{slugify(title)}.md"
        path = destination / filename
        path.write_text(build_document(title, ordinal), encoding="utf-8")
        written.append(path)

    for filename, content in KNOWLEDGE_DOCS.items():
        path = destination / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return written


def main() -> None:
    written = generate_corpus()
    print(f"Generated {len(written)} corpus documents in {written[0].parent}")


if __name__ == "__main__":
    main()
