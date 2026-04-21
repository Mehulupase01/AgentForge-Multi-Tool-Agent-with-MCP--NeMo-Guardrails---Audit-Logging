"""Add review records for the security officer."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "009_reviews"
down_revision = "008_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "target_type",
            sa.Enum("plan", "tool_call", "llm_output", "agent_run", name="review_target_type"),
            nullable=False,
        ),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_role", sa.String(length=32), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum("approved", "rejected", "flagged", name="review_verdict"),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_records_task_id", "review_records", ["task_id"])
    op.create_index("ix_review_records_target", "review_records", ["target_type", "target_id"])
    op.create_index("ix_review_records_verdict", "review_records", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_review_records_verdict", table_name="review_records")
    op.drop_index("ix_review_records_target", table_name="review_records")
    op.drop_index("ix_review_records_task_id", table_name="review_records")
    op.drop_table("review_records")
