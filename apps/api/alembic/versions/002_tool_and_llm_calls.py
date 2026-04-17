"""Create tool_calls and llm_calls."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "002_tool_and_llm_calls"
down_revision = "006_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_step_id", sa.Uuid(), nullable=False),
        sa.Column("server_name", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("required_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_step_id"], ["task_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_calls_server_tool", "tool_calls", ["server_name", "tool_name"])
    op.create_index("ix_tool_calls_task_step_id", "tool_calls", ["task_step_id"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_step_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("completion", sa.Text(), nullable=True),
        sa.Column("input_rails_json", sa.JSON(), nullable=True),
        sa.Column("output_rails_json", sa.JSON(), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_step_id"], ["task_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_task_step_id", "llm_calls", ["task_step_id"])
    op.create_index("ix_llm_calls_blocked", "llm_calls", ["blocked"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_blocked", table_name="llm_calls")
    op.drop_index("ix_llm_calls_task_step_id", table_name="llm_calls")
    op.drop_table("llm_calls")

    op.drop_index("ix_tool_calls_task_step_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_server_tool", table_name="tool_calls")
    op.drop_table("tool_calls")
