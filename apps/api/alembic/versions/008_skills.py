"""Add skills and skill invocations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "008_skills"
down_revision = "007_multi_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agent_role", sa.String(length=32), nullable=False),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("knowledge_refs_json", sa.JSON(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_skills_name_version"),
    )
    op.create_index("ix_skills_agent_role", "skills", ["agent_role"])

    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("task_step_id", sa.Uuid(), nullable=False),
        sa.Column("policy_checks_json", sa.JSON(), nullable=False),
        sa.Column("injected_knowledge_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["task_step_id"], ["task_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_invocations_skill_id", "skill_invocations", ["skill_id"])
    op.create_index("ix_skill_invocations_task_step_id", "skill_invocations", ["task_step_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_invocations_task_step_id", table_name="skill_invocations")
    op.drop_index("ix_skill_invocations_skill_id", table_name="skill_invocations")
    op.drop_table("skill_invocations")

    op.drop_index("ix_skills_agent_role", table_name="skills")
    op.drop_table("skills")
