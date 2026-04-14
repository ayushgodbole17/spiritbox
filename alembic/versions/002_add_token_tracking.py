"""add token and cost tracking columns to entries

Revision ID: 002
Revises: 001
Create Date: 2025-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entries", sa.Column("prompt_tokens", sa.Integer, server_default="0"))
    op.add_column("entries", sa.Column("completion_tokens", sa.Integer, server_default="0"))
    op.add_column("entries", sa.Column("embedding_tokens", sa.Integer, server_default="0"))
    op.add_column("entries", sa.Column("estimated_cost_usd", sa.Float, server_default="0.0"))


def downgrade() -> None:
    op.drop_column("entries", "estimated_cost_usd")
    op.drop_column("entries", "embedding_tokens")
    op.drop_column("entries", "completion_tokens")
    op.drop_column("entries", "prompt_tokens")
