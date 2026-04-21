"""formalize the entry_embeddings table under Alembic

Revision ID: 005
Revises: 004
Create Date: 2026-04-21

The table has historically been created at runtime by
`app.memory.vector_store.init_schema()`. Migration 003 already ALTERs this
table, so on a fresh DB that migration would fail. This revision makes Alembic
authoritative for the table's existence using `IF NOT EXISTS` semantics so
existing prod DBs are unaffected.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EMBED_DIMS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS entry_embeddings (
            entry_id      UUID PRIMARY KEY,
            user_id       TEXT NOT NULL DEFAULT 'default',
            raw_text      TEXT,
            summary       TEXT,
            categories    TEXT[],
            sentence_tags TEXT,
            entry_date    TIMESTAMPTZ DEFAULT NOW(),
            embedding     vector({_EMBED_DIMS})
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS entry_embeddings_ivfflat_idx
        ON entry_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS entry_embeddings_ivfflat_idx")
    op.execute("DROP TABLE IF EXISTS entry_embeddings")
