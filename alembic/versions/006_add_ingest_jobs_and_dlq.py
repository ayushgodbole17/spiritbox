"""ingest_jobs + reminder_dead_letters tables (Phase D)

Revision ID: 006
Revises: 005
Create Date: 2026-04-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingest_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("filename", sa.String()),
        sa.Column("entry_id", UUID(as_uuid=True)),
        sa.Column("result_json", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ingest_jobs_user_id", "ingest_jobs", ["user_id"])
    op.create_index("ix_ingest_jobs_status", "ingest_jobs", ["status"])
    op.create_index("ix_ingest_jobs_created_at", "ingest_jobs", ["created_at"])

    op.create_table(
        "reminder_dead_letters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("events.id")),
        sa.Column("user_email", sa.String()),
        sa.Column("description", sa.Text()),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("resolved", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_retried_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reminder_dead_letters_event_id", "reminder_dead_letters", ["event_id"])
    op.create_index("ix_reminder_dead_letters_resolved", "reminder_dead_letters", ["resolved"])
    op.create_index("ix_reminder_dead_letters_created_at", "reminder_dead_letters", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_reminder_dead_letters_created_at", table_name="reminder_dead_letters")
    op.drop_index("ix_reminder_dead_letters_resolved", table_name="reminder_dead_letters")
    op.drop_index("ix_reminder_dead_letters_event_id", table_name="reminder_dead_letters")
    op.drop_table("reminder_dead_letters")

    op.drop_index("ix_ingest_jobs_created_at", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_status", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_user_id", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
