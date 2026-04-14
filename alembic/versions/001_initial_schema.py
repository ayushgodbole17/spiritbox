"""initial schema — users, entries, events, sentence_tags, eval_runs

Revision ID: 001
Revises: None
Create Date: 2025-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("google_sub", sa.String, unique=True, nullable=False, index=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("name", sa.String),
        sa.Column("picture", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("raw_text", sa.Text),
        sa.Column("summary", sa.Text),
        sa.Column("model_tier", sa.String),
        sa.Column("cache_hit", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", UUID(as_uuid=True), sa.ForeignKey("entries.id")),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("reminder_time", sa.DateTime(timezone=True)),
        sa.Column("scheduler_job", sa.String),
        sa.Column("reminded", sa.Boolean, server_default=sa.text("false")),
    )

    op.create_table(
        "sentence_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", UUID(as_uuid=True), sa.ForeignKey("entries.id")),
        sa.Column("sentence", sa.Text),
        sa.Column("categories", sa.ARRAY(sa.String)),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True)),
        sa.Column("classifier_precision", sa.Float),
        sa.Column("classifier_recall", sa.Float),
        sa.Column("entity_f1", sa.Float),
        sa.Column("prompt_version", sa.String),
        sa.Column("passed", sa.Boolean),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("sentence_tags")
    op.drop_table("events")
    op.drop_table("entries")
    op.drop_table("users")
