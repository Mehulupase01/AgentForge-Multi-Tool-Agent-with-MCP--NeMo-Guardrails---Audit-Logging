"""Create approvals and link tool calls to approval requests."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "003_approvals"
down_revision = "002_tool_and_llm_calls"
branch_labels = None
depends_on = None


risk_level = sa.Enum("low", "medium", "high", name="risk_level")
approval_decision = sa.Enum("pending", "approved", "rejected", name="approval_decision")


def upgrade() -> None:
    bind = op.get_bind()
    risk_level.create(bind, checkfirst=True)
    approval_decision.create(bind, checkfirst=True)

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_step_id", sa.Uuid(), nullable=True),
        sa.Column("risk_level", risk_level, nullable=False),
        sa.Column("risk_reason", sa.Text(), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision", approval_decision, nullable=False, server_default="pending"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_step_id"], ["task_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_decision", "approvals", ["decision"])
    op.create_index("ix_approvals_requested_at", "approvals", ["requested_at"])

    with op.batch_alter_table("tool_calls", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("approval_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tool_calls_approval_id_approvals",
            "approvals",
            ["approval_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_tool_calls_approval_id", ["approval_id"])


def downgrade() -> None:
    with op.batch_alter_table("tool_calls", recreate="always") as batch_op:
        batch_op.drop_index("ix_tool_calls_approval_id")
        batch_op.drop_constraint("fk_tool_calls_approval_id_approvals", type_="foreignkey")
        batch_op.drop_column("approval_id")

    op.drop_index("ix_approvals_requested_at", table_name="approvals")
    op.drop_index("ix_approvals_decision", table_name="approvals")
    op.drop_index("ix_approvals_task_id", table_name="approvals")
    op.drop_table("approvals")

    bind = op.get_bind()
    approval_decision.drop(bind, checkfirst=True)
    risk_level.drop(bind, checkfirst=True)
