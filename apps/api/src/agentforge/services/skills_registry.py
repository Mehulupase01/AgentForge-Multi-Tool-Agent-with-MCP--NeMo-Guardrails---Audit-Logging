from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.config import settings
from agentforge.database import get_session_factory
from agentforge.models.agent_run import AgentRole
from agentforge.models.skill import Skill, SkillInvocation
from agentforge.models.task import Task, TaskStatus
from agentforge.models.task_step import TaskStep
from agentforge.services.audit_service import AuditService

REPO_ROOT = Path(__file__).resolve().parents[5]
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
ALLOWED_POLICY_KEYS = {
    "max_results_per_call",
    "forbid_fields",
    "require_approval_if",
    "topic_scope",
    "rate_limit",
}


class SkillsRegistryConflictError(RuntimeError):
    pass


class SkillsRegistryValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActiveSkill:
    id: UUID
    name: str
    version: str
    description: str
    agent_role: AgentRole
    tools: list[str]
    knowledge_refs: list[str]
    policy: dict[str, Any]
    source_path: str
    content_hash: str
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class SkillContext:
    task_id: UUID
    session_id: UUID
    user_prompt: str
    handoff_reason: str
    handoff_payload: dict[str, Any]
    agent_role: AgentRole


@dataclass(slots=True)
class PolicyEvaluation:
    allowed: bool = True
    requires_approval: bool = False
    violation_reason: str | None = None
    approval_reason: str | None = None
    reroute_role: AgentRole | None = None
    policy_checks: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class SkillDispatchResult:
    agent_result: Any
    step_output: Any
    policy_checks: dict[str, dict[str, Any]]
    injected_knowledge_tokens: int


@dataclass(slots=True)
class SkillReloadSummary:
    loaded: int
    updated: int
    removed: int


class SkillsRegistry:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        audit_service: AuditService | None = None,
        skills_path: str | Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._audit_service = audit_service or AuditService()
        self._skills_path = skills_path or settings.skills_path
        self._active_skills_by_role: dict[AgentRole, ActiveSkill] = {}
        self._active_skills_by_id: dict[UUID, ActiveSkill] = {}
        self._knowledge_cache: dict[str, int] = {}
        self._rate_limit_windows: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    def resolve_path(self) -> Path:
        path = Path(self._skills_path)
        return path if path.is_absolute() else REPO_ROOT / path

    def list_active_skills(self, *, agent_role: AgentRole | None = None) -> list[ActiveSkill]:
        values = sorted(
            self._active_skills_by_id.values(),
            key=lambda skill: (skill.agent_role.value, skill.name, skill.version),
        )
        if agent_role is None:
            return values
        return [skill for skill in values if skill.agent_role == agent_role]

    def get_active_skill(self, skill_id: UUID) -> ActiveSkill | None:
        return self._active_skills_by_id.get(skill_id)

    def get_skill_for_role(self, role: AgentRole) -> ActiveSkill:
        skill = self._active_skills_by_role.get(role)
        if skill is None:
            raise KeyError(f"No active skill configured for role '{role.value}'")
        return skill

    async def ensure_loaded(self) -> None:
        if self._active_skills_by_role:
            return
        await self.load_all()

    async def load_all(self) -> SkillReloadSummary:
        async with self._lock:
            skill_files = sorted(self.resolve_path().glob("*.yml"))
            loaded_documents = [self._read_skill_file(path) for path in skill_files]

            async with self._session_factory() as session:
                existing_rows = list((await session.execute(select(Skill))).scalars())
                existing_by_key = {(row.name, row.version): row for row in existing_rows}
                previous_active = set(self._active_skills_by_id)
                active_skills: dict[UUID, ActiveSkill] = {}
                active_roles: dict[AgentRole, ActiveSkill] = {}
                updated = 0

                for document in loaded_documents:
                    row = existing_by_key.get((document["name"], document["version"]))
                    is_update = row is not None and row.content_hash != document["content_hash"]
                    if row is None:
                        row = Skill(
                            name=document["name"],
                            version=document["version"],
                            description=document["description"],
                            agent_role=document["agent_role"].value,
                            tools_json=document["tools"],
                            knowledge_refs_json=document["knowledge_refs"],
                            policy_json=document["policy"],
                            source_path=document["source_path"],
                            content_hash=document["content_hash"],
                            registered_at=datetime.now(UTC),
                        )
                        session.add(row)
                        await session.flush()
                    else:
                        row.description = document["description"]
                        row.agent_role = document["agent_role"].value
                        row.tools_json = document["tools"]
                        row.knowledge_refs_json = document["knowledge_refs"]
                        row.policy_json = document["policy"]
                        row.source_path = document["source_path"]
                        row.content_hash = document["content_hash"]
                    if is_update:
                        updated += 1

                    active_skill = ActiveSkill(
                        id=row.id,
                        name=row.name,
                        version=row.version,
                        description=row.description,
                        agent_role=document["agent_role"],
                        tools=list(row.tools_json),
                        knowledge_refs=list(row.knowledge_refs_json),
                        policy=dict(row.policy_json),
                        source_path=row.source_path,
                        content_hash=row.content_hash,
                        registered_at=row.registered_at,
                    )
                    active_skills[active_skill.id] = active_skill
                    active_roles[active_skill.agent_role] = active_skill

                removed_skill_ids = previous_active - set(active_skills)
                if removed_skill_ids and await self._removed_skills_in_use(session, removed_skill_ids):
                    raise SkillsRegistryConflictError(
                        "Cannot remove a skill version that is currently being used by a running task.",
                    )

                await session.commit()

            self._active_skills_by_id = active_skills
            self._active_skills_by_role = active_roles
            return SkillReloadSummary(
                loaded=len(active_skills),
                updated=updated,
                removed=len(removed_skill_ids),
            )

    def evaluate(
        self,
        *,
        skill: ActiveSkill,
        tool_name: str,
        args: dict[str, Any],
        task_context: SkillContext,
    ) -> PolicyEvaluation:
        evaluation = PolicyEvaluation()
        checks = evaluation.policy_checks

        checks["tool_allowlist"] = {
            "pass": tool_name in set(skill.tools),
            "detail": {"tool_name": tool_name},
        }
        if not checks["tool_allowlist"]["pass"]:
            evaluation.allowed = False
            evaluation.violation_reason = f"Skill {skill.name} cannot call tool {tool_name}."
            return evaluation

        combined_text = self._combined_context_text(task_context).lower()
        topic_scope = list(skill.policy.get("topic_scope") or [])
        if topic_scope:
            matched_topics = [topic for topic in topic_scope if topic.lower() in combined_text]
            checks["topic_scope"] = {
                "pass": bool(matched_topics),
                "detail": {"matched_topics": matched_topics, "scope": topic_scope},
            }
            if not matched_topics:
                evaluation.allowed = False
                evaluation.violation_reason = (
                    f"Skill {skill.name} is out of scope for the current request."
                )
                evaluation.reroute_role = self.suggest_reroute_role(
                    combined_text,
                    excluding=skill.agent_role,
                )
                return evaluation

        approval_matches: list[dict[str, Any]] = []
        approval_rules = list(skill.policy.get("require_approval_if") or [])
        for rule in approval_rules:
            if not isinstance(rule, dict):
                continue
            if "join_contains" in rule:
                sql = str(args.get("sql", ""))
                terms = [str(item).lower() for item in rule.get("join_contains", [])]
                matched = "join" in sql.lower() and any(term in sql.lower() for term in terms)
                checks.setdefault("require_approval_if", {"pass": True, "detail": []})
                checks["require_approval_if"]["detail"].append(
                    {"rule": "join_contains", "matched": matched, "terms": terms},
                )
                if matched:
                    approval_matches.append({"join_contains": terms})
            if rule.get("no_limit_clause"):
                sql = str(args.get("sql", ""))
                matched = bool(sql) and LIMIT_PATTERN.search(sql) is None
                checks.setdefault("require_approval_if", {"pass": True, "detail": []})
                checks["require_approval_if"]["detail"].append(
                    {"rule": "no_limit_clause", "matched": matched},
                )
                if matched:
                    approval_matches.append({"no_limit_clause": True})
            if "cost_usd_gt" in rule:
                checks.setdefault("require_approval_if", {"pass": True, "detail": []})
                checks["require_approval_if"]["detail"].append(
                    {"rule": "cost_usd_gt", "matched": False, "threshold": rule["cost_usd_gt"]},
                )

        if approval_matches:
            checks["require_approval_if"]["pass"] = False
            evaluation.requires_approval = True
            evaluation.approval_reason = (
                f"Skill {skill.name} requires approval before calling {tool_name}: "
                f"{json.dumps(approval_matches, ensure_ascii=True)}"
            )

        return evaluation

    async def await_rate_limit(self, skill: ActiveSkill) -> dict[str, Any]:
        policy = skill.policy.get("rate_limit") or {}
        per_minute = int(policy.get("per_minute", 0) or 0)
        if per_minute <= 0:
            return {"pass": True, "detail": {"applied": False}}

        window = self._rate_limit_windows.setdefault(skill.name, deque())
        while True:
            now = asyncio.get_running_loop().time()
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) < per_minute:
                window.append(now)
                return {"pass": True, "detail": {"applied": True, "per_minute": per_minute}}
            await asyncio.sleep(max(0.01, 60 - (now - window[0])))

    def apply_post_policies(
        self,
        *,
        skill: ActiveSkill,
        result: Any,
        prior_checks: dict[str, dict[str, Any]],
    ) -> SkillDispatchResult:
        checks = dict(prior_checks)
        processed = result
        metadata: dict[str, Any] = {}

        forbid_fields = [str(field) for field in skill.policy.get("forbid_fields") or []]
        if forbid_fields:
            processed, redaction_applied = self._redact_forbidden_fields(processed, forbid_fields)
            checks["forbid_fields"] = {
                "pass": True,
                "detail": {"applied": redaction_applied, "fields": forbid_fields},
            }

        max_results = skill.policy.get("max_results_per_call")
        if isinstance(max_results, int) and max_results > 0:
            processed, truncated = self._truncate_results(processed, max_results)
            checks["max_results_per_call"] = {
                "pass": True,
                "detail": {"applied": truncated, "limit": max_results},
            }
            if truncated:
                metadata["truncated_to"] = max_results

        injected_knowledge_tokens = self._knowledge_token_count(skill)
        step_output = processed
        if metadata:
            step_output = {"result": processed, "metadata": metadata}

        return SkillDispatchResult(
            agent_result=processed,
            step_output=step_output,
            policy_checks=checks,
            injected_knowledge_tokens=injected_knowledge_tokens,
        )

    async def record_invocation(
        self,
        *,
        task_step_id: UUID,
        task_id: UUID,
        session_id: UUID,
        skill: ActiveSkill,
        policy_checks: dict[str, dict[str, Any]],
        injected_knowledge_tokens: int,
    ) -> None:
        async with self._session_factory() as session:
            invocation = SkillInvocation(
                skill_id=skill.id,
                task_step_id=task_step_id,
                policy_checks_json=policy_checks,
                injected_knowledge_tokens=injected_knowledge_tokens,
                invoked_at=datetime.now(UTC),
            )
            session.add(invocation)
            await session.flush()
            await self._audit_service.record_event(
                session,
                event_type="skill.invoked",
                actor=skill.agent_role.value,
                payload={
                    "task_id": str(task_id),
                    "task_step_id": str(task_step_id),
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "policy_checks": policy_checks,
                    "injected_knowledge_tokens": injected_knowledge_tokens,
                },
                session_id=session_id,
                task_id=task_id,
                commit=False,
            )
            await session.commit()

    async def record_policy_violation(
        self,
        *,
        task_id: UUID,
        session_id: UUID,
        role: AgentRole,
        skill: ActiveSkill,
        tool_name: str,
        reason: str,
        policy_checks: dict[str, dict[str, Any]],
    ) -> None:
        async with self._session_factory() as session:
            await self._audit_service.record_event(
                session,
                event_type="skill.policy_violation",
                actor=role.value,
                payload={
                    "task_id": str(task_id),
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "tool_name": tool_name,
                    "reason": reason,
                    "policy_checks": policy_checks,
                },
                session_id=session_id,
                task_id=task_id,
            )

    def suggest_reroute_role(self, text: str, *, excluding: AgentRole | None = None) -> AgentRole | None:
        lowered = text.lower()
        best_match: tuple[int, AgentRole] | None = None
        for role, skill in self._active_skills_by_role.items():
            if excluding is not None and role == excluding:
                continue
            scope = [str(item).lower() for item in skill.policy.get("topic_scope") or []]
            score = sum(1 for item in scope if item in lowered)
            if score <= 0:
                continue
            if best_match is None or score > best_match[0]:
                best_match = (score, role)
        return best_match[1] if best_match else None

    async def _removed_skills_in_use(self, session: AsyncSession, removed_ids: set[UUID]) -> bool:
        if not removed_ids:
            return False
        active_statuses = {
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.AWAITING_APPROVAL,
        }
        rows = list(
            (
                await session.execute(
                    select(SkillInvocation.skill_id, Task.status)
                    .join(TaskStep, SkillInvocation.task_step_id == TaskStep.id)
                    .join(Task, TaskStep.task_id == Task.id)
                    .where(SkillInvocation.skill_id.in_(removed_ids))
                )
            ).all()
        )
        for _, task_status in rows:
            if task_status in active_statuses:
                return True
        return False

    def _read_skill_file(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            raise SkillsRegistryValidationError(f"Skill file must parse to an object: {path}")

        required_keys = {
            "name",
            "version",
            "agent_role",
            "description",
            "tools",
            "knowledge_refs",
            "policy",
        }
        missing = sorted(required_keys - set(parsed))
        if missing:
            raise SkillsRegistryValidationError(f"Missing required keys in {path.name}: {', '.join(missing)}")

        role = AgentRole(str(parsed["agent_role"]))
        tools = [str(item) for item in parsed["tools"]]
        knowledge_refs = [str(item) for item in parsed["knowledge_refs"]]
        policy = parsed["policy"] if isinstance(parsed["policy"], dict) else {}
        unknown_policy_keys = sorted(set(policy) - ALLOWED_POLICY_KEYS)
        if unknown_policy_keys:
            raise SkillsRegistryValidationError(
                f"Skill policy in {path.name} contains unsupported keys: {', '.join(unknown_policy_keys)}",
            )
        self._validate_policy(policy, path)

        try:
            source_path = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            source_path = path.as_posix()

        return {
            "name": str(parsed["name"]),
            "version": str(parsed["version"]),
            "agent_role": role,
            "description": str(parsed["description"]),
            "tools": tools,
            "knowledge_refs": knowledge_refs,
            "policy": policy,
            "source_path": source_path,
            "content_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _validate_policy(policy: dict[str, Any], path: Path) -> None:
        if "max_results_per_call" in policy and not isinstance(policy["max_results_per_call"], int):
            raise SkillsRegistryValidationError(f"max_results_per_call must be an integer in {path.name}")
        if "forbid_fields" in policy and not isinstance(policy["forbid_fields"], list):
            raise SkillsRegistryValidationError(f"forbid_fields must be a list in {path.name}")
        if "require_approval_if" in policy and not isinstance(policy["require_approval_if"], list):
            raise SkillsRegistryValidationError(f"require_approval_if must be a list in {path.name}")
        if "topic_scope" in policy and not isinstance(policy["topic_scope"], list):
            raise SkillsRegistryValidationError(f"topic_scope must be a list in {path.name}")
        rate_limit = policy.get("rate_limit")
        if rate_limit is not None:
            if not isinstance(rate_limit, dict) or not isinstance(rate_limit.get("per_minute"), int):
                raise SkillsRegistryValidationError(f"rate_limit.per_minute must be an integer in {path.name}")

    @staticmethod
    def _combined_context_text(task_context: SkillContext) -> str:
        payload = json.dumps(task_context.handoff_payload, sort_keys=True, ensure_ascii=True)
        return " ".join(
            [
                task_context.user_prompt,
                task_context.handoff_reason,
                payload,
                task_context.agent_role.value,
            ]
        )

    def _knowledge_token_count(self, skill: ActiveSkill) -> int:
        total = 0
        for ref in skill.knowledge_refs:
            if ref not in self._knowledge_cache:
                path = Path(ref)
                resolved = path if path.is_absolute() else REPO_ROOT / path
                text = resolved.read_text(encoding="utf-8")
                self._knowledge_cache[ref] = len(text.split())
            total += self._knowledge_cache[ref]
        return total

    @staticmethod
    def _redact_forbidden_fields(result: Any, fields: list[str]) -> tuple[Any, bool]:
        if isinstance(result, list):
            redacted = []
            applied = False
            for item in result:
                updated, item_applied = SkillsRegistry._redact_forbidden_fields(item, fields)
                redacted.append(updated)
                applied = applied or item_applied
            return redacted, applied
        if isinstance(result, dict):
            updated = {}
            applied = False
            for key, value in result.items():
                if key in fields:
                    applied = True
                    continue
                updated[key] = value
            return updated, applied
        return result, False

    @staticmethod
    def _truncate_results(result: Any, limit: int) -> tuple[Any, bool]:
        if isinstance(result, list) and len(result) > limit:
            return result[:limit], True
        return result, False


_skills_registry: SkillsRegistry | None = None


def _get_or_create_skills_registry(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> SkillsRegistry:
    global _skills_registry
    if _skills_registry is None or (
        session_factory is not None and _skills_registry._session_factory is not session_factory
    ):
        _skills_registry = SkillsRegistry(
            session_factory=session_factory or get_session_factory(),
        )
    return _skills_registry


def get_skills_registry() -> SkillsRegistry:
    return _get_or_create_skills_registry()
