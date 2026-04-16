"""Create corpus_documents."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "006_corpus"
down_revision = "004_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corpus_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filename"),
    )
    op.create_index("ix_corpus_documents_filename", "corpus_documents", ["filename"])


def downgrade() -> None:
    op.drop_index("ix_corpus_documents_filename", table_name="corpus_documents")
    op.drop_table("corpus_documents")
