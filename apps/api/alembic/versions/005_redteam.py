"""Create redteam runs and results."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "005_redteam"
down_revision = "003_approvals"
branch_labels = None
depends_on = None


redteam_category = sa.Enum(
    "prompt_injection",
    "data_exfil",
    "pii_leak",
    "jailbreak",
    "tool_abuse",
    "goal_hijack",
    name="redteam_category",
)
redteam_outcome = sa.Enum(
    "blocked",
    "allowed_safe",
    "allowed_unsafe",
    name="redteam_outcome",
)


def upgrade() -> None:
    bind = op.get_bind()
    redteam_category.create(bind, checkfirst=True)
    redteam_outcome.create(bind, checkfirst=True)

    op.create_table(
        "redteam_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("total_scenarios", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safety_compliance_pct", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "redteam_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("category", redteam_category, nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_outcome", redteam_outcome, nullable=False),
        sa.Column("actual_outcome", redteam_outcome, nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["redteam_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_redteam_results_run_id", "redteam_results", ["run_id"])
    op.create_index("ix_redteam_results_category_passed", "redteam_results", ["category", "passed"])


def downgrade() -> None:
    op.drop_index("ix_redteam_results_category_passed", table_name="redteam_results")
    op.drop_index("ix_redteam_results_run_id", table_name="redteam_results")
    op.drop_table("redteam_results")
    op.drop_table("redteam_runs")

    bind = op.get_bind()
    redteam_outcome.drop(bind, checkfirst=True)
    redteam_category.drop(bind, checkfirst=True)
