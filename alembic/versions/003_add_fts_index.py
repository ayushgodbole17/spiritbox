"""add full-text search tsvector column and GIN index to entry_embeddings

Revision ID: 003
Revises: 002
Create Date: 2025-05-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE entry_embeddings
        ADD COLUMN IF NOT EXISTS fts tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(raw_text, '') || ' ' || coalesce(summary, ''))
        ) STORED
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS entry_embeddings_fts_idx
        ON entry_embeddings USING gin (fts)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS entry_embeddings_fts_idx")
    op.execute("ALTER TABLE entry_embeddings DROP COLUMN IF EXISTS fts")
