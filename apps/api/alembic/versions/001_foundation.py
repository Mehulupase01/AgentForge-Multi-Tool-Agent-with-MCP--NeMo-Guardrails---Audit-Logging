"""Create sessions, tasks, and task_steps."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "001_foundation"
down_revision = None
branch_labels = None
depends_on = None


session_status = sa.Enum(
    "active",
    "completed",
    "failed",
    "terminated",
    name="session_status",
)
task_status = sa.Enum(
    "planning",
    "executing",
    "awaiting_approval",
    "completed",
    "failed",
    "rejected",
    name="task_status",
)
step_type = sa.Enum(
    "llm_reasoning",
    "tool_call",
    "approval_gate",
    "guardrail_block",
    "user_response",
    name="step_type",
)
step_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    name="step_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    session_status.create(bind, checkfirst=True)
    task_status.create(bind, checkfirst=True)
    step_type.create(bind, checkfirst=True)
    step_status.create(bind, checkfirst=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("status", session_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("status", task_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "task_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("step_type", step_type, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_steps_task_id_ordinal", "task_steps", ["task_id", "ordinal"], unique=True)
    op.create_index("ix_task_steps_status", "task_steps", ["status"])


def downgrade() -> None:
    op.drop_index("ix_task_steps_status", table_name="task_steps")
    op.drop_index("ix_task_steps_task_id_ordinal", table_name="task_steps")
    op.drop_table("task_steps")

    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_session_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    bind = op.get_bind()
    step_status.drop(bind, checkfirst=True)
    step_type.drop(bind, checkfirst=True)
    task_status.drop(bind, checkfirst=True)
    session_status.drop(bind, checkfirst=True)
