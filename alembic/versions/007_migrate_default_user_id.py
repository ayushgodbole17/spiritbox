"""migrate legacy user_id='default' rows onto the real user (Phase A follow-up)

Revision ID: 007
Revises: 006
Create Date: 2026-04-22

Pre-Phase-A, `get_current_user` silently returned 'default' on missing/invalid
tokens, so every ingested row landed with user_id='default'. Post-Phase-A the
dependency returns the real JWT sub (the User.id UUID), so those legacy rows
became invisible to the authenticated user.

This migration fixes the drift — but only when the users table contains
exactly one user, so it's safe to run on a future multi-user DB as a no-op.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.exec_driver_sql("SELECT COUNT(*) FROM users")
    user_count = result.scalar() or 0

    if user_count != 1:
        # Either no users yet (fresh DB) or multi-tenant — do nothing.
        # A multi-user DB would need a manual mapping; we won't guess.
        op.execute("SELECT 'skipping: user count != 1'")
        return

    # Pick the single real user and rewrite every 'default' row onto them.
    # Tables that carry a user_id column (as of 007):
    #   entries.user_id                 — VARCHAR
    #   entry_embeddings.user_id        — TEXT
    #   habits.user_id                  — VARCHAR
    op.execute(
        """
        UPDATE entries
           SET user_id = (SELECT id::text FROM users LIMIT 1)
         WHERE user_id = 'default'
        """
    )
    op.execute(
        """
        UPDATE entry_embeddings
           SET user_id = (SELECT id::text FROM users LIMIT 1)
         WHERE user_id = 'default'
        """
    )
    op.execute(
        """
        UPDATE habits
           SET user_id = (SELECT id::text FROM users LIMIT 1)
         WHERE user_id = 'default'
        """
    )


def downgrade() -> None:
    # Intentional no-op — we do not re-orphan rows onto 'default'.
    pass
