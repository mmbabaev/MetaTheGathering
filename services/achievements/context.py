"""Контекст оценки одного турнира — данные, общие для всех правил.

Собирается один раз: результаты из парингов переводятся из строковых имён AetherHub в
``user_id`` (иначе каждое правило дёргало бы ``find_user_by_name`` заново), применяется
гейт зачёта §2.5, отдельно фиксируются те, кто в зачёт не попал — их показываем в отчёте,
чтобы «был 4-0, а ачивки нет» не выглядело багом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.achievements.history import (
    AchievementHistory,
    PlayerRecord,
    counts_for_achievements,
    display_name,
    tournament_date,
)

# Почему участник не попал в зачёт ачивок.
SKIP_NO_DECK = "колода не записана"
SKIP_NOT_SELF = "колоду записал не он"
SKIP_PLACEHOLDER = "нет аккаунта в боте"


@dataclass(frozen=True)
class SkippedPlayer:
    user_id: Optional[int]
    name: str
    reason: str


@dataclass
class TournamentContext:
    """Всё, что нужно правилам про конкретный турнир."""

    tournament: models.Tournament
    history: AchievementHistory
    participants: dict[int, models.Participant] = field(default_factory=dict)  # user_id -> participant
    users: dict[int, models.User] = field(default_factory=dict)  # user_id -> user
    eligible_user_ids: set[int] = field(default_factory=set)
    records: dict[int, PlayerRecord] = field(default_factory=dict)
    undefeated_user_ids: set[int] = field(default_factory=set)
    skipped: list[SkippedPlayer] = field(default_factory=list)

    @property
    def played_at(self) -> datetime:
        return tournament_date(self.tournament)

    def deck_name(self, user_id: int) -> Optional[str]:
        participant = self.participants.get(user_id)
        if participant is None or participant.archetype is None:
            return None
        return participant.archetype.name

    def name(self, user_id: int) -> str:
        user = self.users.get(user_id)
        return display_name(user) if user is not None else f"user#{user_id}"


def build_context(
    db: Session, tournament_id: int, history: Optional[AchievementHistory] = None
) -> Optional[TournamentContext]:
    """Собрать контекст завершённого турнира. None — турнира нет.

    Незавершённость (нет парингов / не у всех матчей счёт) здесь не проверяется:
    это решает вызывающий сервис, чтобы отличить «рано» от «нечего считать».
    """
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None:
        return None

    history = history if history is not None else AchievementHistory(db)
    ctx = TournamentContext(tournament=tournament, history=history)

    rows = db.execute(
        select(models.Participant, models.User)
        .join(models.User, models.Participant.user_id == models.User.id)
        .where(models.Participant.tournament_id == tournament_id)
    ).all()
    for participant, user in rows:
        ctx.participants[user.id] = participant
        ctx.users[user.id] = user
        if user.tg_id <= 0:
            ctx.skipped.append(SkippedPlayer(user.id, display_name(user), SKIP_PLACEHOLDER))
            continue
        if participant.archetype_id is None:
            ctx.skipped.append(SkippedPlayer(user.id, display_name(user), SKIP_NO_DECK))
            continue
        if not counts_for_achievements(participant, user):
            ctx.skipped.append(SkippedPlayer(user.id, display_name(user), SKIP_NOT_SELF))
            continue
        ctx.eligible_user_ids.add(user.id)

    for user_id in ctx.eligible_user_ids:
        record = history.record_for(tournament_id, user_id)
        if record is None:
            continue  # игрок записался, но в парингах его нет (не пришёл / имя не сматчилось)
        ctx.records[user_id] = record
        if history.is_undefeated(tournament_id, user_id):
            ctx.undefeated_user_ids.add(user_id)

    return ctx
