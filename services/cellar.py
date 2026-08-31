"""Deck-lending catalog and exclusive reservations for the Edinorog cellar."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from core import models
from core.config import settings
from services.archetype import ArchetypeService
from services.cellar_sheet import CatalogEntry, CellarCatalogSourceError, GoogleSheetsCellarCatalog
from services.names import has_complete_person_name
from services.tournament import TournamentService

logger = logging.getLogger(__name__)

CELLAR_CLUB_NAME = "Edinorog"
CELLAR_TIMEZONE = ZoneInfo("Europe/Moscow")
CELLAR_WEEKDAYS = (0, 3)  # Monday and Thursday


def _allowed_cellar_recipients(candidates: list[int | None]) -> list[int]:
    allowed = settings.notify_allowed_ids
    recipients: list[int] = []
    for tg_id in candidates:
        if tg_id is None or tg_id in recipients:
            continue
        if allowed is not None and tg_id not in allowed:
            continue
        recipients.append(tg_id)
    return recipients


def cellar_notification_recipients(db: Session) -> list[int]:
    """Recipients of the single pre-event summary for the current environment."""

    if settings.DEBUG:
        return _allowed_cellar_recipients([settings.OWNER_CHAT_ID])

    candidates: list[int | None] = [*settings.cellar_coordinator_tg_ids]
    if settings.cellar_coordinator_usernames:
        matching_ids: dict[str, set[int]] = {}
        rows = db.execute(
            select(func.lower(models.User.username), models.User.tg_id).where(
                models.User.tg_id > 0,
                func.lower(models.User.username).in_(settings.cellar_coordinator_usernames),
            )
        )
        for username, tg_id in rows:
            matching_ids.setdefault(username, set()).add(tg_id)
        for username in settings.cellar_coordinator_usernames:
            ids = matching_ids.get(username, set())
            if len(ids) == 1:
                candidates.append(next(iter(ids)))
            elif len(ids) > 1:
                logger.warning("Skipping ambiguous cellar coordinator username with %d matches", len(ids))
    candidates.append(settings.OWNER_CHAT_ID)
    return _allowed_cellar_recipients(candidates)


def cellar_immediate_notification_recipients(db: Session) -> list[int]:
    """Production cellar owners receive booking/cancellation DMs; debug stays owner-only."""

    recipients = cellar_notification_recipients(db)
    if not recipients:
        return []
    preferences = dict(
        db.execute(
            select(models.User.tg_id, models.User.notify_cellar_reservations).where(models.User.tg_id.in_(recipients))
        ).all()
    )
    # Missing legacy users keep the default-on behaviour until they open the bot.
    return [tg_id for tg_id in recipients if preferences.get(tg_id, True)]


def can_view_cellar_overview(tg_id: int, username: str | None) -> bool:
    """The owner and production coordinators may inspect upcoming reservations."""

    if settings.OWNER_CHAT_ID is not None and tg_id == settings.OWNER_CHAT_ID:
        return True
    if settings.DEBUG:
        return False
    normalized_username = username.lstrip("@").casefold() if username else None
    return tg_id in settings.cellar_coordinator_tg_ids or normalized_username in settings.cellar_coordinator_usernames


class CellarReservationError(ValueError):
    pass


class CellarDeckUnavailable(CellarReservationError):
    pass


class CellarUserAlreadyReserved(CellarReservationError):
    pass


class CellarInvalidUserName(CellarReservationError):
    pass


class CellarInvalidEventDate(CellarReservationError):
    pass


class CellarReservationNotFound(CellarReservationError):
    pass


@dataclass(frozen=True)
class ReservationResult:
    reservation: models.CellarDeckReservation
    created: bool


def _copies(key: str, name: str, count: int, *, archetype: str | None = None, notes: str | None = None):
    for number in range(1, count + 1):
        suffix = f" #{number}" if count > 1 else ""
        yield CatalogEntry(
            f"bootstrap:{key}:{number}",
            f"{name}{suffix}",
            archetype or name,
            notes=notes,
        )


# Offline fallback for a completely empty database when Google Sheets is unavailable.
BOOTSTRAP_CATALOG = [
    CatalogEntry("bootstrap:ponza:gruul-ramp", "Ponza — с надписью Gruul Ramp", "Ponza"),
    CatalogEntry("bootstrap:ponza:unsigned", "Ponza — без подписи", "Ponza"),
    *_copies("golgari-pestilence", "Golgari Pestilence", 1),
    *_copies("boggles", "Boggles", 1),
    *_copies("white-weenie", "White Weenie", 2),
    CatalogEntry("bootstrap:altar-tron:1", "Altar Tron #1", "Altar Tron"),
    CatalogEntry("bootstrap:altar-tron:2", "Altar Tron #2", "Altar Tron", notes="Без камней"),
    *_copies("dredge", "Dredge", 1),
    *_copies("rakdos-madness", "Rakdos Madness", 2),
    *_copies("u-faeries", "U Faeries", 2),
    *_copies("jund-midrange", "Jund Midrange", 2, notes="С инфильтраторами"),
    *_copies("cycling-storm", "Cycling Storm", 1),
    *_copies("rw-inside-out", "RW Inside Out", 2),
    *_copies("u-terror", "U Terror", 2),
    *_copies("walls-combo", "Walls Combo", 1),
    *_copies("flicker-tron", "Flicker Tron", 1),
    *_copies("ruby-storm", "Ruby Storm", 1),
    *_copies("jeskai-ephemerate", "Jeskai Ephemerate", 1),
    *_copies("infect", "Infect", 1),
    *_copies("r-rally", "R Rally", 1),
    *_copies("uw-caw-gates", "UW Caw Gates", 1),
    *_copies("gruul-ramp", "Gruul Ramp", 1),
    *_copies("white-heroic", "White Heroic", 2),
    *_copies("gw-glintblade", "GW Glintblade", 1),
    *_copies(
        "grixis-affinity",
        "Grixis Affinity",
        1,
        notes="В сайдборде заменить 2 канонады на Breath Weapon",
    ),
    *_copies(
        "pizza-combo",
        "Pizza Combo",
        1,
        notes="В сайдборде заменить 2 канонады на Breath Weapon",
    ),
    *_copies("monored-madness", "Monored Madness", 1),
    *_copies("mono-b-sacrifice", "Mono B Sacrifice", 1),
    *_copies("ub-terror", "UB Terror", 1),
]


def next_cellar_dates(today: date | None = None, count: int = 4) -> list[date]:
    today = today or datetime.now(CELLAR_TIMEZONE).date()
    dates: list[date] = []
    offset = 0
    while len(dates) < count:
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in CELLAR_WEEKDAYS:
            dates.append(candidate)
        offset += 1
    return dates


class CellarService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_bootstrap_catalog(self) -> int:
        existing = set(self.db.execute(select(models.CellarDeck.source_key)).scalars())
        rows = [entry for entry in BOOTSTRAP_CATALOG if entry.source_key not in existing]
        for entry in rows:
            self.db.add(
                models.CellarDeck(
                    source_key=entry.source_key,
                    name=entry.name,
                    archetype_name=entry.archetype_name,
                    notes=entry.notes,
                )
            )
        if rows:
            self.db.commit()
        return len(rows)

    def sync_catalog(self, entries: list[CatalogEntry], *, synced_at: datetime | None = None) -> tuple[int, int, int]:
        """Upsert sheet rows and retain removed rows as inactive reservation history."""

        if not entries:
            raise CellarCatalogSourceError("Пустой каталог нельзя синхронизировать.")
        synced_at = synced_at or models.utc_now()
        existing = {deck.source_key: deck for deck in self.db.execute(select(models.CellarDeck)).scalars().all()}
        seen: set[str] = set()
        created = updated = 0
        for entry in entries:
            if entry.source_key in seen:
                raise CellarCatalogSourceError(f"Дублирующийся ключ колоды: {entry.source_key}")
            seen.add(entry.source_key)
            deck = existing.get(entry.source_key)
            if deck is None:
                deck = models.CellarDeck(
                    source_key=entry.source_key, name=entry.name, archetype_name=entry.archetype_name
                )
                self.db.add(deck)
                created += 1
            else:
                updated += 1
            deck.name = entry.name
            deck.archetype_name = entry.archetype_name
            deck.decklist_url = entry.decklist_url
            deck.notes = entry.notes
            deck.decklist_updated_on = entry.decklist_updated_on
            deck.source_position = entry.source_position
            deck.available = entry.available
            deck.active = True
            deck.updated_at = synced_at

        deactivated = 0
        for deck in existing.values():
            if deck.source_key not in seen and deck.active:
                deck.active = False
                deactivated += 1
        self.db.commit()
        return created, updated, deactivated

    def ensure_catalog(self, *, source: GoogleSheetsCellarCatalog | None = None) -> tuple[int, int, int] | None:
        """Populate an empty database; regular refreshes are owned by the weekly job."""

        sheet_count, missing_positions = self.db.execute(
            select(
                func.count(models.CellarDeck.id),
                func.count(models.CellarDeck.id).filter(models.CellarDeck.source_position.is_(None)),
            ).where(
                models.CellarDeck.active.is_(True),
                models.CellarDeck.source_key.like("gsheet:%"),
            )
        ).one()
        if sheet_count and not missing_positions:
            return None

        try:
            return self.sync_catalog((source or GoogleSheetsCellarCatalog()).fetch())
        except CellarCatalogSourceError:
            logger.warning("Не удалось обновить каталог ячейки из Google Sheets", exc_info=True)
            self.ensure_bootstrap_catalog()
            return None
        except IntegrityError:
            # Concurrent process startup can race while populating a new database.
            # The unique index chooses the winner; the other process can use its result.
            self.db.rollback()
            logger.info("Каталог ячейки уже синхронизирован другим процессом")
            return None

    def catalog(self, event_date: date) -> list[models.CellarDeck]:
        return (
            self.db.execute(
                select(models.CellarDeck)
                .options(selectinload(models.CellarDeck.reservations).selectinload(models.CellarDeckReservation.user))
                .where(models.CellarDeck.active.is_(True))
                .order_by(models.CellarDeck.name, models.CellarDeck.id)
            )
            .scalars()
            .all()
        )

    def catalog_for_user(
        self,
        event_date: date,
        user_id: int,
        *,
        previous_limit: int = 3,
    ) -> list[models.CellarDeck]:
        """Put the current booking and recent distinct deck choices before the catalog."""

        decks = self.catalog(event_date)
        reservations = (
            self.db.execute(
                select(models.CellarDeckReservation)
                .where(models.CellarDeckReservation.user_id == user_id)
                .order_by(
                    models.CellarDeckReservation.created_at.desc(),
                    models.CellarDeckReservation.id.desc(),
                )
            )
            .scalars()
            .all()
        )

        current_deck_id = next(
            (
                reservation.deck_id
                for reservation in reservations
                if reservation.event_date == event_date and reservation.cancelled_at is None
            ),
            None,
        )
        recent_deck_ids: list[int] = []
        for reservation in reservations:
            if reservation.deck_id == current_deck_id or reservation.deck_id in recent_deck_ids:
                continue
            if len(recent_deck_ids) < previous_limit:
                recent_deck_ids.append(reservation.deck_id)

        preferred_ids = ([current_deck_id] if current_deck_id is not None else []) + recent_deck_ids
        priority = {deck_id: index for index, deck_id in enumerate(preferred_ids)}
        fallback = len(priority)
        return sorted(decks, key=lambda deck: (priority.get(deck.id, fallback), deck.name.casefold(), deck.id))

    @staticmethod
    def reservation_for(deck: models.CellarDeck, event_date: date) -> models.CellarDeckReservation | None:
        return next(
            (
                reservation
                for reservation in deck.reservations
                if reservation.event_date == event_date and reservation.cancelled_at is None
            ),
            None,
        )

    def active_reservations(self, event_date: date) -> list[models.CellarDeckReservation]:
        return (
            self.db.execute(
                select(models.CellarDeckReservation)
                .options(
                    selectinload(models.CellarDeckReservation.deck),
                    selectinload(models.CellarDeckReservation.user),
                )
                .where(
                    models.CellarDeckReservation.event_date == event_date,
                    models.CellarDeckReservation.cancelled_at.is_(None),
                )
                .order_by(models.CellarDeck.name, models.CellarDeckReservation.id)
                .join(models.CellarDeck)
            )
            .scalars()
            .all()
        )

    def reserve(self, *, deck_id: int, user_id: int, event_date: date, today: date | None = None) -> ReservationResult:
        self._validate_event_date(event_date, today=today)
        deck = self.db.get(models.CellarDeck, deck_id)
        if deck is None or not deck.active or not deck.available:
            raise CellarDeckUnavailable("Эта колода недоступна.")
        user = self.db.get(models.User, user_id)
        if user is None or not has_complete_person_name(user.first_name, user.last_name):
            raise CellarInvalidUserName("Для бронирования укажите фамилию и имя в настройках бота.")

        existing = self.db.execute(
            select(models.CellarDeckReservation).where(
                models.CellarDeckReservation.user_id == user_id,
                models.CellarDeckReservation.event_date == event_date,
                models.CellarDeckReservation.cancelled_at.is_(None),
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.deck_id == deck_id:
                return ReservationResult(existing, created=False)
            raise CellarUserAlreadyReserved("На эту дату у вас уже забронирована другая колода.")

        reservation = models.CellarDeckReservation(deck_id=deck_id, user_id=user_id, event_date=event_date)
        self.db.add(reservation)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise CellarDeckUnavailable("Эту колоду только что забронировал другой игрок.") from exc
        self.db.refresh(reservation)
        self.attach_to_tournament(reservation)
        return ReservationResult(reservation, created=True)

    def cancel(self, *, reservation_id: int, user_id: int) -> models.CellarDeckReservation:
        reservation = self.db.execute(
            select(models.CellarDeckReservation)
            .options(selectinload(models.CellarDeckReservation.deck))
            .where(
                models.CellarDeckReservation.id == reservation_id,
                models.CellarDeckReservation.user_id == user_id,
                models.CellarDeckReservation.cancelled_at.is_(None),
            )
        ).scalar_one_or_none()
        if reservation is None:
            raise CellarReservationNotFound("Активная бронь не найдена.")
        self._undo_tournament_assignment(reservation)
        reservation.cancelled_at = models.utc_now()
        self.db.commit()
        return reservation

    def attach_event_to_tournament(self, event_date: date, tournament_id: int) -> int:
        reservations = self.active_reservations(event_date)
        attached = 0
        for reservation in reservations:
            if self._apply_to_tournament(reservation, tournament_id):
                attached += 1
        return attached

    def attach_to_tournament(self, reservation: models.CellarDeckReservation) -> bool:
        tournament = self._event_tournament(reservation.event_date)
        return bool(tournament and self._apply_to_tournament(reservation, tournament.id))

    def mark_group_announced(self, reservation_id: int) -> None:
        reservation = self.db.get(models.CellarDeckReservation, reservation_id)
        if reservation is not None and reservation.group_announced_at is None:
            reservation.group_announced_at = models.utc_now()
            self.db.commit()

    def coordinator_delivery(self, event_date: date, recipient_tg_id: int) -> models.CellarCoordinatorReminder:
        row = self.db.execute(
            select(models.CellarCoordinatorReminder).where(
                models.CellarCoordinatorReminder.event_date == event_date,
                models.CellarCoordinatorReminder.recipient_tg_id == recipient_tg_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = models.CellarCoordinatorReminder(event_date=event_date, recipient_tg_id=recipient_tg_id)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def finish_coordinator_delivery(self, row: models.CellarCoordinatorReminder, error: str | None = None) -> None:
        row.attempts += 1
        row.last_error = error[:255] if error else None
        if error is None:
            row.delivered_at = models.utc_now()
        self.db.commit()

    @staticmethod
    def _validate_event_date(event_date: date, today: date | None = None) -> None:
        today = today or datetime.now(CELLAR_TIMEZONE).date()
        if event_date not in next_cellar_dates(today, count=4):
            raise CellarInvalidEventDate(
                "Колоды из ячейки можно бронировать на один из четырёх ближайших турниров по понедельникам и четвергам."
            )

    def _event_tournament(self, event_date: date) -> models.Tournament | None:
        start_local = datetime.combine(event_date, time.min, tzinfo=CELLAR_TIMEZONE)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        return self.db.execute(
            select(models.Tournament)
            .where(
                models.Tournament.club == CELLAR_CLUB_NAME,
                models.Tournament.status == models.TournamentStatus.REGISTRATION,
                models.Tournament.registration_close_at >= start_utc,
                models.Tournament.registration_close_at < end_utc,
            )
            .order_by(models.Tournament.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _apply_to_tournament(self, reservation: models.CellarDeckReservation, tournament_id: int) -> bool:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None or tournament.status != models.TournamentStatus.REGISTRATION:
            return False
        if not has_complete_person_name(reservation.user.first_name, reservation.user.last_name):
            return False
        participant_svc = TournamentService(self.db)
        participant = participant_svc.get_participant(tournament_id, reservation.user_id)
        archetype = ArchetypeService(self.db).get_or_create_by_name(reservation.deck.archetype_name)
        created = False
        if participant is None:
            participant = participant_svc.register_participant(
                tournament_id=tournament_id,
                user_id=reservation.user_id,
                archetype_id=archetype.id,
                deck_added_by_tg_id=reservation.user.tg_id,
            )
            created = True
        else:
            reservation.previous_archetype_id = participant.archetype_id
            reservation.previous_deck_added_by_tg_id = participant.deck_added_by_tg_id
            reservation.previous_deck_deferred = participant.deck_deferred
            participant_svc.set_participant_archetype(
                participant_id=participant.id,
                archetype_id=archetype.id,
                deck_added_by_tg_id=reservation.user.tg_id,
            )
        reservation.tournament_id = tournament_id
        reservation.participant_id = participant.id
        reservation.applied_archetype_id = archetype.id
        reservation.participant_created = created
        self.db.commit()
        return True

    def _undo_tournament_assignment(self, reservation: models.CellarDeckReservation) -> None:
        if not reservation.participant_id or not reservation.applied_archetype_id:
            return
        participant = self.db.get(models.Participant, reservation.participant_id)
        if (
            participant is None
            or participant.archetype_id != reservation.applied_archetype_id
            or participant.tournament.status != models.TournamentStatus.REGISTRATION
        ):
            return
        if reservation.participant_created:
            TournamentService(self.db).unregister_participant(participant.tournament_id, participant.user_id)
        else:
            participant.archetype_id = reservation.previous_archetype_id
            participant.deck_added_by_tg_id = reservation.previous_deck_added_by_tg_id
            if reservation.previous_deck_deferred is not None:
                participant.deck_deferred = reservation.previous_deck_deferred
            participant.updated_at = models.utc_now()
            self.db.commit()


def reservation_user_name(user: models.User) -> str:
    return (
        user.display_name or " ".join(part for part in (user.first_name, user.last_name) if part) or f"id{user.tg_id}"
    )


def reservation_user_username(user: models.User) -> str:
    return f"@{user.username}" if user.username else "без @username"


def cellar_deck_display_name(deck: models.CellarDeck) -> str:
    return deck.display_name


def format_group_reservation(reservation: models.CellarDeckReservation, *, cancelled: bool = False) -> str:
    action = "отменил(а) бронь" if cancelled else "забронировал(а)"
    return (
        f"🗄 {reservation_user_name(reservation.user)} "
        f"({reservation_user_username(reservation.user)}) {action} колоды из ячейки:\n"
        f"{cellar_deck_display_name(reservation.deck)} — {reservation.event_date.strftime('%d.%m.%Y')}"
    )


def format_coordinator_summary(event_date: date, reservations: list[models.CellarDeckReservation]) -> str:
    lines = [f"🗄 Колоды из ячейки на {event_date.strftime('%d.%m.%Y')}:"]
    lines.extend(
        f"• {reservation_user_name(reservation.user)} — {reservation_user_username(reservation.user)} — "
        f"{cellar_deck_display_name(reservation.deck)}"
        for reservation in reservations
    )
    return "\n".join(lines)


def format_coordinator_overview(
    reservations_by_date: list[tuple[date, list[models.CellarDeckReservation]]],
    *,
    max_length: int = 3400,
) -> str:
    """Compact coordinator-only list for the `/cellar` date menu."""

    rows = [
        (
            f"• {event_date.strftime('%d.%m.%Y')} — {reservation_user_name(reservation.user)} — "
            f"{reservation_user_username(reservation.user)} — {cellar_deck_display_name(reservation.deck)}"
        )
        for event_date, reservations in reservations_by_date
        for reservation in reservations
    ]
    if not rows:
        return "Брони на ближайшие турниры: пока нет."

    lines = ["Брони на ближайшие турниры:"]
    for index, row in enumerate(rows):
        omitted = len(rows) - index
        suffix = f"\n… ещё {omitted}" if omitted else ""
        if len("\n".join([*lines, row])) + len(suffix) > max_length:
            lines.append(f"… ещё {omitted}")
            break
        lines.append(row)
    return "\n".join(lines)
