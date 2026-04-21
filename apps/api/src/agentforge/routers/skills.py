from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agentforge.models.agent_run import AgentRole
from agentforge.schemas.common import Envelope, Pagination
from agentforge.schemas.skill import SkillReloadResponse, SkillResponse
from agentforge.services.skills_registry import (
    ActiveSkill,
    SkillsRegistry,
    SkillsRegistryConflictError,
    get_skills_registry,
)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _to_skill_response(skill: ActiveSkill) -> SkillResponse:
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        agent_role=skill.agent_role,
        tools=skill.tools,
        knowledge_refs=skill.knowledge_refs,
        policy=skill.policy,
        source_path=skill.source_path,
        content_hash=skill.content_hash,
        registered_at=skill.registered_at,
    )


@router.get("", response_model=Envelope[SkillResponse])
async def list_skills(
    skills_registry: Annotated[SkillsRegistry, Depends(get_skills_registry)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    agent_role: AgentRole | None = Query(default=None),
) -> Envelope[SkillResponse]:
    if not skills_registry.list_active_skills():
        await skills_registry.load_all()
    skills = skills_registry.list_active_skills(agent_role=agent_role)
    total = len(skills)
    sliced = skills[(page - 1) * per_page : page * per_page]
    return Envelope(
        data=[_to_skill_response(skill) for skill in sliced],
        meta=Pagination(page=page, per_page=per_page, total=total),
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: UUID,
    skills_registry: Annotated[SkillsRegistry, Depends(get_skills_registry)],
) -> SkillResponse:
    if not skills_registry.list_active_skills():
        await skills_registry.load_all()
    skill = skills_registry.get_active_skill(skill_id)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "Skill not found",
                "detail": {"skill_id": str(skill_id)},
            },
        )
    return _to_skill_response(skill)


@router.post("/reload", response_model=SkillReloadResponse)
async def reload_skills(
    skills_registry: Annotated[SkillsRegistry, Depends(get_skills_registry)],
) -> SkillReloadResponse:
    try:
        return await skills_registry.load_all()
    except SkillsRegistryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": str(exc),
                "detail": {},
            },
        ) from exc
