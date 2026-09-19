"""rename active Endstep-ru tournament to Konetskhod Pauper

Revision ID: b516420f583a
Revises: e5b393c08316
Create Date: 2026-09-19
"""

import re
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b516420f583a"
down_revision: Union[str, Sequence[str], None] = "e5b393c08316"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENDSTEP_RU = "Endstep-ru"
KONETSKHOD = "Концеход"

_OLD_NAME_RE = re.compile(rf"{re.escape(ENDSTEP_RU)} Pauper[^\n]*")
_NEW_NAME_RE = re.compile(rf"{re.escape(KONETSKHOD)} Pauper #\d+")


def _endstep_tournaments():
    return sa.table(
        "tournaments",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("club", sa.String),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime),
    )


def _registration_messages():
    return sa.table(
        "tournament_registration_messages",
        sa.column("id", sa.Integer),
        sa.column("tournament_id", sa.Integer),
        sa.column("base_text", sa.String),
    )


def _is_endstep(club_col, title_col):
    return sa.or_(club_col == ENDSTEP_RU, title_col.ilike(f"%{ENDSTEP_RU}%"))


def upgrade() -> None:
    connection = op.get_bind()
    tournaments = _endstep_tournaments()
    messages = _registration_messages()

    total = connection.execute(
        sa.select(sa.func.count()).select_from(tournaments).where(_is_endstep(tournaments.c.club, tournaments.c.title))
    ).scalar_one()
    active = connection.execute(
        sa.select(tournaments.c.id, tournaments.c.title)
        .where(_is_endstep(tournaments.c.club, tournaments.c.title), tournaments.c.status != "CLOSED")
        .order_by(tournaments.c.created_at, tournaments.c.id)
    ).all()
    if not active:
        return

    for index, (tournament_id, title) in enumerate(active):
        number = total - len(active) + 1 + index
        new_name = f"{KONETSKHOD} Pauper #{number}"
        new_title = _OLD_NAME_RE.sub(new_name, title)
        if new_title != title:
            connection.execute(
                sa.update(tournaments).where(tournaments.c.id == tournament_id).values(title=new_title)
            )
        connection.execute(
            sa.update(messages)
            .where(messages.c.tournament_id == tournament_id)
            .values(
                base_text=sa.func.replace(messages.c.base_text, f"{ENDSTEP_RU} Pauper", new_name),
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    tournaments = _endstep_tournaments()
    messages = _registration_messages()

    rows = connection.execute(
        sa.select(tournaments.c.id, tournaments.c.title).where(
            tournaments.c.title.ilike(f"%{KONETSKHOD} Pauper #%")
        )
    ).all()
    tournament_ids = []
    for tournament_id, title in rows:
        new_title = _NEW_NAME_RE.sub(f"{ENDSTEP_RU} Pauper", title)
        if new_title != title:
            tournament_ids.append(tournament_id)
            connection.execute(
                sa.update(tournaments).where(tournaments.c.id == tournament_id).values(title=new_title)
            )
    if not tournament_ids:
        return
    for message_id, base_text in connection.execute(
        sa.select(messages.c.id, messages.c.base_text).where(messages.c.tournament_id.in_(tournament_ids))
    ).all():
        connection.execute(
            sa.update(messages)
            .where(messages.c.id == message_id)
            .values(base_text=_NEW_NAME_RE.sub(f"{ENDSTEP_RU} Pauper", base_text)),
        )
