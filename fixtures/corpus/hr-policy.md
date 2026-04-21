---
title: HR Policy Guardrails
topic: workforce policy
summary: Internal HR guidance for safe workforce reporting and protected field handling.
---

# HR Policy Guardrails

Workforce analytics in AgentForge should prefer aggregate and bounded views over broad extracts. Reports may discuss staffing, project allocation, and department trends, but sensitive compensation details require elevated review before they are exposed to operators or downstream systems.

Protected fields such as `salary_band` should not appear in normal analyst outputs. When a workflow explicitly requests joins or filters involving compensation data, the system should pause for human review instead of silently widening access.

Analyst-facing summaries should focus on staffing patterns, project assignments, and delivery planning. If a request can be satisfied without touching protected fields, the safer path should be chosen by default.
