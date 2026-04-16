"""add habits and habit_logs tables

Revision ID: 004
Revises: 003
Create Date: 2026-04-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String()),
        sa.Column("cadence", sa.String(), server_default="occasional"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_logged_at", sa.DateTime(timezone=True)),
        sa.Column("streak_days", sa.Integer(), server_default="0"),
    )
    op.create_index("ix_habits_user_id", "habits", ["user_id"])

    op.create_table(
        "habit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("habit_id", UUID(as_uuid=True), sa.ForeignKey("habits.id", ondelete="CASCADE")),
        sa.Column("entry_id", UUID(as_uuid=True), sa.ForeignKey("entries.id")),
        sa.Column("logged_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_habit_logs_habit_logged", "habit_logs", ["habit_id", "logged_at"])


def downgrade() -> None:
    op.drop_index("ix_habit_logs_habit_logged", table_name="habit_logs")
    op.drop_table("habit_logs")
    op.drop_index("ix_habits_user_id", table_name="habits")
    op.drop_table("habits")
