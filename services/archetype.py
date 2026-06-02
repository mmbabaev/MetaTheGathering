from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from sqlalchemy import func, nulls_last, select
from sqlalchemy.orm import Session

from core import models

logger = logging.getLogger(__name__)


@dataclass
class ArchetypeItem:
    id: int
    name: str


class ArchetypeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_archetypes(self) -> List[ArchetypeItem]:
        stmt = select(models.Archetype).order_by(models.Archetype.name.asc())
        rows = self.db.execute(stmt).scalars().all()
        return [ArchetypeItem(id=a.id, name=a.name) for a in rows]

    def list_top_archetypes(self, n: int = 10) -> List[ArchetypeItem]:
        """Топ-N архетипов по числу использований в турнирах прошедших фазу регистрации.

        Участники турниров в статусе REGISTRATION не учитываются — иначе только что
        назначенные колоды всплывали бы в топе и загрязняли меню выбора.
        """
        past_registration = (
            select(models.Tournament.id).where(models.Tournament.status != models.TournamentStatus.REGISTRATION)
        ).scalar_subquery()

        stmt = (
            select(
                models.Archetype.id,
                models.Archetype.name,
                func.count(models.Participant.id).label("usage_count"),
            )
            .outerjoin(
                models.Participant,
                (models.Participant.archetype_id == models.Archetype.id)
                & models.Participant.tournament_id.in_(past_registration),
            )
            .where(models.Archetype.is_custom.is_(False))
            .group_by(models.Archetype.id, models.Archetype.name, models.Archetype.meta_rank)
            .order_by(
                func.count(models.Participant.id).desc(),
                nulls_last(models.Archetype.meta_rank.asc()),
                models.Archetype.name.asc(),
            )
            .limit(n)
        )
        rows = self.db.execute(stmt).all()
        return [ArchetypeItem(id=row.id, name=row.name) for row in rows]

    def list_user_recent_archetypes(self, tg_id: int) -> List[ArchetypeItem]:
        """История архетипов пользователя: самые свежие первыми, без дублей.

        Источники (в порядке приоритета):
        1. Участие в прошлых турнирах (самые новые первыми)
        2. user_deck_history (DataLens import; ORDER BY id ASC = порядок по числу матчей)
        """
        user = self.db.execute(select(models.User).where(models.User.tg_id == tg_id)).scalar_one_or_none()
        if not user:
            return []

        seen: set[int] = set()
        recent_ids: list[int] = []

        part_stmt = (
            select(models.Participant.archetype_id)
            .where(
                models.Participant.user_id == user.id,
                models.Participant.archetype_id.isnot(None),
            )
            .order_by(models.Participant.created_at.desc())
        )
        tournament_ids: list[int] = []
        for (aid,) in self.db.execute(part_stmt).all():
            if aid not in seen:
                seen.add(aid)
                recent_ids.append(aid)
                tournament_ids.append(aid)

        hist_stmt = (
            select(models.UserDeckHistory.archetype_id)
            .where(models.UserDeckHistory.user_id == user.id)
            .order_by(models.UserDeckHistory.id.asc())
        )
        datalens_ids: list[int] = []
        for (aid,) in self.db.execute(hist_stmt).all():
            if aid not in seen:
                seen.add(aid)
                recent_ids.append(aid)
                datalens_ids.append(aid)

        all_arch = {a.id: a for a in self.list_archetypes()}

        if logger.isEnabledFor(logging.DEBUG):
            t_names = [all_arch[i].name for i in tournament_ids if i in all_arch]
            d_names = [all_arch[i].name for i in datalens_ids if i in all_arch]
            logger.debug(
                "archetype_menu tg_id=%s | tournaments(%d)=%s | datalens(%d)=%s",
                tg_id,
                len(t_names),
                t_names,
                len(d_names),
                d_names,
            )

        return [all_arch[aid] for aid in recent_ids if aid in all_arch]

    def list_user_tournament_archetypes(
        self, user_id: int, exclude_tournament_id: int | None = None, limit: int = 3
    ) -> List[ArchetypeItem]:
        """Колоды, которыми пользователь играл в ТУРНИРАХ (самые свежие первыми, без дублей).

        Только реальное участие в турнирах — без UserDeckHistory. Опционально исключает
        один турнир (например, текущий). Возвращает не более `limit` уникальных архетипов.
        """
        stmt = (
            select(models.Participant.archetype_id, models.Archetype.name)
            .join(models.Archetype, models.Participant.archetype_id == models.Archetype.id)
            .where(
                models.Participant.user_id == user_id,
                models.Participant.archetype_id.isnot(None),
            )
            .order_by(models.Participant.created_at.desc())
        )
        if exclude_tournament_id is not None:
            stmt = stmt.where(models.Participant.tournament_id != exclude_tournament_id)

        seen: set[int] = set()
        items: List[ArchetypeItem] = []
        for aid, name in self.db.execute(stmt).all():
            if aid in seen:
                continue
            seen.add(aid)
            items.append(ArchetypeItem(id=aid, name=name))
            if len(items) >= limit:
                break
        return items

    def list_archetypes_for_user(self, tg_id: int, total: int = 10) -> List[ArchetypeItem]:
        """Устаревший метод для обратной совместимости тестов."""
        recent = self.list_user_recent_archetypes(tg_id)
        recent_set = {a.id for a in recent}
        rest = [a for a in self.list_archetypes() if a.id not in recent_set]
        return (recent + rest)[:total]

    def get_or_create_by_name(self, name: str, is_custom: bool = False) -> models.Archetype:
        """Найти архетип по имени или создать новый."""
        stmt = select(models.Archetype).where(models.Archetype.name == name)
        archetype = self.db.execute(stmt).scalar_one_or_none()
        if archetype:
            return archetype
        archetype = models.Archetype(name=name.strip(), is_custom=is_custom)
        self.db.add(archetype)
        self.db.commit()
        self.db.refresh(archetype)
        return archetype
