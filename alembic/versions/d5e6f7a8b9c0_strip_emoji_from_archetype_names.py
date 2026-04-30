"""Strip leading emoji from archetype names and deduplicate.

Revision ID: c1d2e3f4a5b6
Revises: b5c6d7e8f9a0
Create Date: 2026-05-01

"""

from __future__ import annotations

import re
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEADING_EMOJI_RE = re.compile(r"^[^\w]+", re.UNICODE)


def _strip(name: str) -> str:
    return _LEADING_EMOJI_RE.sub("", name).strip()


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(text("SELECT id, name FROM archetypes")).fetchall()
    for arch_id, name in rows:
        clean = _strip(name)
        if clean == name:
            continue

        # Check if clean name already exists
        existing = conn.execute(text("SELECT id FROM archetypes WHERE name = :n"), {"n": clean}).fetchone()

        if existing:
            target_id = existing[0]
            # Re-point all participants to the canonical archetype
            conn.execute(
                text("UPDATE participants SET archetype_id = :tid WHERE archetype_id = :sid"),
                {"tid": target_id, "sid": arch_id},
            )
            conn.execute(text("DELETE FROM archetypes WHERE id = :id"), {"id": arch_id})
        else:
            conn.execute(
                text("UPDATE archetypes SET name = :n WHERE id = :id"),
                {"n": clean, "id": arch_id},
            )


def downgrade() -> None:
    pass
