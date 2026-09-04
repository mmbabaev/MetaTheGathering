"""Durable plans for manually scheduled tournament creation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.clubs import ClubIdentity, club_identities
from core.config import Club
from core.schemas import TournamentCreate, TournamentRead
from services.cellar import CELLAR_CLUB_NAME, CellarService
from services.club_settings import ClubAnnouncementSettingsService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.tournament import TournamentService
from services.utils import get_tournament

logger = logging.getLogger(__name__)


class InvalidCreationPlan(ValueError):
    pass


@dataclass(frozen=True)
class PreparedTournament:
    plan_id: int
    tournament: TournamentRead
    club: Club
    event_at_local: datetime


def club_identity(name: str) -> ClubIdentity | None:
    return next((identity for identity in club_identities() if identity.name == name), None)


def identity_to_club(identity: ClubIdentity, chat_id: int | None = None) -> Club:
    return Club(
        name=identity.name,
        chat_id=chat_id or 0,
        schedules=[],
        is_online=identity.is_online,
        aetherhub_url=identity.aetherhub_url,
        title_prefix=identity.title_prefix,
        timezone=identity.timezone,
    )


class TournamentCreationPlanService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_plan(
        self,
        *,
        club_name: str,
        created_by_tg_id: int,
        announce_at: datetime,
        event_at: datetime,
    ) -> models.TournamentCreationPlan:
        identity = club_identity(club_name)
        if identity is None:
            raise InvalidCreationPlan("Клуб не найден.")
        if announce_at.tzinfo is not None or event_at.tzinfo is not None:
            raise InvalidCreationPlan("Внутренние даты должны быть в UTC без timezone.")
        if event_at <= announce_at:
            raise InvalidCreationPlan("Турнир должен начаться после публикации регистрации.")
        existing = self.db.execute(
            select(models.TournamentCreationPlan.id)
            .where(
                models.TournamentCreationPlan.club_name == club_name,
                models.TournamentCreationPlan.event_at == event_at,
                models.TournamentCreationPlan.status.in_(("pending", "completed")),
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            raise InvalidCreationPlan("Турнир этого клуба на выбранное время уже запланирован.")
        target = ClubAnnouncementSettingsService(self.db).current_target(identity)
        row = models.TournamentCreationPlan(
            club_name=club_name,
            created_by_tg_id=created_by_tg_id,
            announce_at=announce_at,
            event_at=event_at,
            announcement_chat_id=target.chat_id,
            announcement_chat_label=target.label,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, plan_id: int) -> models.TournamentCreationPlan | None:
        return self.db.get(models.TournamentCreationPlan, plan_id)

    def list_due(self, now: datetime | None = None, limit: int = 20) -> list[models.TournamentCreationPlan]:
        now = now or models.utc_now()
        return list(
            self.db.execute(
                select(models.TournamentCreationPlan)
                .where(
                    models.TournamentCreationPlan.status == "pending",
                    models.TournamentCreationPlan.announce_at <= now,
                )
                .order_by(models.TournamentCreationPlan.announce_at, models.TournamentCreationPlan.id)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def prepare_tournament(self, plan_id: int) -> PreparedTournament:
        plan = self.get(plan_id)
        if plan is None or plan.status != "pending":
            raise InvalidCreationPlan("План создания уже обработан или не найден.")
        identity = club_identity(plan.club_name)
        if identity is None:
            raise InvalidCreationPlan("Клуб не найден.")
        if plan.event_at <= models.utc_now():
            raise InvalidCreationPlan("Время турнира уже прошло.")
        club = identity_to_club(identity, plan.announcement_chat_id)
        local_tz = ZoneInfo(identity.timezone)
        event_at_local = plan.event_at.replace(tzinfo=timezone.utc).astimezone(local_tz)

        if plan.tournament_id is None:
            date_str = event_at_local.strftime("%Y-%m-%d")
            club_slug = "-".join(identity.name.lower().split())
            tournament = TournamentService(self.db).create_tournament(
                TournamentCreate(
                    title=f"{identity.title_prefix}{identity.name} Pauper {event_at_local.strftime('%d.%m.%Y')}",
                    chat_id=plan.announcement_chat_id or 0,
                    slug=f"{date_str}-{club_slug}-pauper",
                    club=identity.name,
                    is_online=identity.is_online,
                    registration_close_at=plan.event_at,
                )
            )
            plan.tournament_id = tournament.id
            plan.last_error = None
            self.db.commit()
            self._attach_cellar_reservations(identity.name, event_at_local, tournament.id)
        else:
            tournament = TournamentRead.model_validate(get_tournament(self.db, plan.tournament_id))
        return PreparedTournament(plan.id, tournament, club, event_at_local)

    def mark_announced(self, plan_id: int, now: datetime | None = None) -> None:
        plan = self.get(plan_id)
        if plan is None:
            return
        plan.announcement_sent_at = now or models.utc_now()
        plan.status = "completed"
        plan.last_error = None
        self.db.commit()

    def mark_completed_without_announcement(self, plan_id: int) -> None:
        plan = self.get(plan_id)
        if plan is None:
            return
        plan.status = "completed"
        plan.last_error = None
        self.db.commit()

    def record_delivery_error(self, plan_id: int, message: str) -> None:
        plan = self.get(plan_id)
        if plan is None:
            return
        plan.last_error = message[:512]
        self.db.commit()

    def mark_failed(self, plan_id: int, message: str) -> None:
        plan = self.get(plan_id)
        if plan is None:
            return
        plan.status = "failed"
        plan.last_error = message[:512]
        self.db.commit()

    def _attach_cellar_reservations(self, club_name: str, event_at_local: datetime, tournament_id: int) -> None:
        if club_name != CELLAR_CLUB_NAME or not FeatureFlagService(self.db).is_enabled(FeatureFlags.CELLAR_DECKS):
            return
        try:
            CellarService(self.db).attach_event_to_tournament(event_at_local.date(), tournament_id)
        except Exception:
            self.db.rollback()
            logger.exception("Manual tournament creation: cellar reservations failed for #%s", tournament_id)
