"""Add multi-agent runs and task step ownership metadata."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "007_multi_agent"
down_revision = "005_redteam"
branch_labels = None
depends_on = None


agent_role = sa.Enum(
    "orchestrator",
    "analyst",
    "researcher",
    "engineer",
    "secretary",
    "security_officer",
    name="agent_role",
)
agent_run_status = sa.Enum(
    "running",
    "completed",
    "handed_off",
    "failed",
    "rejected",
    name="agent_run_status",
)
step_type_v2 = sa.Enum(
    "llm_reasoning",
    "tool_call",
    "approval_gate",
    "guardrail_block",
    "user_response",
    "reflection",
    "retry",
    name="step_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    agent_role.create(bind, checkfirst=True)
    agent_run_status.create(bind, checkfirst=True)
    if dialect == "postgresql":
        op.execute("ALTER TYPE step_type ADD VALUE IF NOT EXISTS 'reflection'")
        op.execute("ALTER TYPE step_type ADD VALUE IF NOT EXISTS 'retry'")

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("role", agent_role, nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("handoff_reason", sa.Text(), nullable=True),
        sa.Column("handoff_payload_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", agent_run_status, nullable=False, server_default="running"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"])
    op.create_index("ix_agent_runs_role_status", "agent_runs", ["role", "status"])

    with op.batch_alter_table("task_steps", recreate="always") as batch_op:
        if dialect != "postgresql":
            batch_op.alter_column("step_type", existing_type=sa.Enum(name="step_type"), type_=step_type_v2)
        batch_op.add_column(sa.Column("agent_role", agent_role, nullable=False, server_default="orchestrator"))
        batch_op.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("parent_step_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("agent_run_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_task_steps_parent_step_id_task_steps", "task_steps", ["parent_step_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_task_steps_agent_run_id_agent_runs", "agent_runs", ["agent_run_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_task_steps_agent_run_id", ["agent_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("task_steps", recreate="always") as batch_op:
        batch_op.drop_index("ix_task_steps_agent_run_id")
        batch_op.drop_constraint("fk_task_steps_agent_run_id_agent_runs", type_="foreignkey")
        batch_op.drop_constraint("fk_task_steps_parent_step_id_task_steps", type_="foreignkey")
        batch_op.drop_column("agent_run_id")
        batch_op.drop_column("parent_step_id")
        batch_op.drop_column("attempt")
        batch_op.drop_column("agent_role")

    op.drop_index("ix_agent_runs_role_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_task_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    bind = op.get_bind()
    agent_run_status.drop(bind, checkfirst=True)
    agent_role.drop(bind, checkfirst=True)
