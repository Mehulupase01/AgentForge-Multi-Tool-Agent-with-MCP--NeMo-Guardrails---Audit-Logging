"""Add triggers and trigger events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "010_triggers"
down_revision = "009_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source", sa.Enum("github_webhook", "generic_webhook", "schedule", name="trigger_source"), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("enabled", "disabled", name="trigger_status"), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trigger_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trigger_id", sa.Uuid(), sa.ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_headers_json", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "status",
            sa.Enum("received", "accepted", "rejected", "processed", "failed", name="trigger_event_status"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resulting_task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trigger_events_trigger_id", "trigger_events", ["trigger_id"])
    op.create_index("ix_trigger_events_status", "trigger_events", ["status"])

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("trigger_event_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_tasks_trigger_event_id", ["trigger_event_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_trigger_event_id")
        batch_op.drop_column("trigger_event_id")

    op.drop_index("ix_trigger_events_status", table_name="trigger_events")
    op.drop_index("ix_trigger_events_trigger_id", table_name="trigger_events")
    op.drop_table("trigger_events")
    op.drop_table("triggers")
