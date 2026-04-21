"""Add cost and confidence observability tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_observability"
down_revision = "010_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("llm_call_id", sa.Uuid(), sa.ForeignKey("llm_calls.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_role", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("usd_cost", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cost_records_task_id", "cost_records", ["task_id"])
    op.create_index("ix_cost_records_agent_role", "cost_records", ["agent_role"])
    op.create_index("ix_cost_records_model", "cost_records", ["model"])

    op.create_table(
        "confidence_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.Enum("task", "step", "agent_run", name="confidence_scope"), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("heuristic_value", sa.Float(), nullable=False),
        sa.Column("self_reported_value", sa.Float(), nullable=True),
        sa.Column("factors_json", sa.JSON(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_confidence_scores_task_id", "confidence_scores", ["task_id"])
    op.create_index("ix_confidence_scores_target", "confidence_scores", ["scope", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_confidence_scores_target", table_name="confidence_scores")
    op.drop_index("ix_confidence_scores_task_id", table_name="confidence_scores")
    op.drop_table("confidence_scores")

    op.drop_index("ix_cost_records_model", table_name="cost_records")
    op.drop_index("ix_cost_records_agent_role", table_name="cost_records")
    op.drop_index("ix_cost_records_task_id", table_name="cost_records")
    op.drop_table("cost_records")
