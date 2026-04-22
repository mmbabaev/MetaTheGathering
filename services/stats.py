from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models


@dataclass
class MetaRow:
    archetype_id: int
    archetype_name: str
    count: int
    upvotes_sum: int
    downvotes_sum: int


@dataclass
class PlayerStatsRow:
    user_id: int
    username: Optional[str]
    tournaments_played: int
    total_upvotes: int
    total_downvotes: int


class StatsService:
    def __init__(self, db: Session):
        self.db = db

    def get_tournament_meta(self, tournament_id: int) -> List[MetaRow]:
        stmt = (
            select(
                models.Archetype.id.label("archetype_id"),
                models.Archetype.name.label("archetype_name"),
                func.count(models.Participant.id).label("count"),
                func.sum(models.Participant.upvotes_count).label("upvotes_sum"),
                func.sum(models.Participant.downvotes_count).label("downvotes_sum"),
            )
            .join(models.Participant, models.Participant.archetype_id == models.Archetype.id)
            .where(models.Participant.tournament_id == tournament_id)
            .group_by(models.Archetype.id, models.Archetype.name)
            .order_by(func.count(models.Participant.id).desc())
        )

        rows = self.db.execute(stmt).all()
        return [
            MetaRow(
                archetype_id=row.archetype_id,
                archetype_name=row.archetype_name,
                count=row.count or 0,
                upvotes_sum=row.upvotes_sum or 0,
                downvotes_sum=row.downvotes_sum or 0,
            )
            for row in rows
        ]

    def get_player_stats(self, user_id: int) -> PlayerStatsRow:
        """
        Простая агрегированная статистика по игроку:
        - сколько турниров играл
        - суммарные up/down по всем турнирам.
        """
        stmt = (
            select(
                models.User.id.label("user_id"),
                models.User.username.label("username"),
                func.count(models.Participant.id.distinct()).label("tournaments_played"),
                func.sum(models.Participant.upvotes_count).label("total_upvotes"),
                func.sum(models.Participant.downvotes_count).label("total_downvotes"),
            )
            .join(models.Participant, models.Participant.user_id == models.User.id)
            .where(models.User.id == user_id)
            .group_by(models.User.id, models.User.username)
        )

        row = self.db.execute(stmt).one_or_none()
        if not row:
            return PlayerStatsRow(
                user_id=user_id,
                username=None,
                tournaments_played=0,
                total_upvotes=0,
                total_downvotes=0,
            )

        return PlayerStatsRow(
            user_id=row.user_id,
            username=row.username,
            tournaments_played=row.tournaments_played or 0,
            total_upvotes=row.total_upvotes or 0,
            total_downvotes=row.total_downvotes or 0,
        )
