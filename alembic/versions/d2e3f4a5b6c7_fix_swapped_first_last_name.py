"""fix swapped first/last name for users where first_name holds a family name

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None

_FAMILY_SUFFIXES = (
    "ов", "ев", "ёв", "ин", "ын", "ый", "ий", "ой",
    "ский", "цкий", "ской", "ная",
    "ных", "ых", "ина", "ева", "ова", "ская",
)


def _looks_like_family_name(word: str) -> bool:
    w = word.lower()
    return any(w.endswith(s) for s in _FAMILY_SUFFIXES)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(text(
        "SELECT id, first_name, last_name FROM users "
        "WHERE first_name IS NOT NULL AND last_name IS NOT NULL "
        "AND first_name != '' AND last_name != ''"
    )).fetchall()

    to_fix = [
        (row.id, row.last_name, row.first_name)
        for row in rows
        if _looks_like_family_name(row.first_name) and not _looks_like_family_name(row.last_name)
    ]

    for user_id, new_first, new_last in to_fix:
        conn.execute(
            text("UPDATE users SET first_name = :fn, last_name = :ln WHERE id = :id"),
            {"fn": new_first, "ln": new_last, "id": user_id},
        )


def downgrade() -> None:
    pass
