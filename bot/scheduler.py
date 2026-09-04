"""Планировщик автоматического создания турниров и импорта AetherHub по расписанию клубов.

⚠️ При добавлении/изменении джоб, времён или расписания клубов ОБЯЗАТЕЛЬНО обнови
`docs/scheduler.md` — это полный перечень автоматических действий по времени и событиям.
"""

import asyncio
import io
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, ContextTypes

from bot.chart import build_chart, build_standings
from bot.deeplink import fill_missing_deeplink, registration_deeplink
from bot.handlers.aetherhub import format_tournament_not_found
from bot.messages import format_decks_revealed, format_meta_gather_completed, format_missing_decks_reminder
from bot.registration_messages import RegistrationMessageRefreshJob
from bot.registration_messages import send_registration_open as _send_registration_open
from bot.telegram.achievements import send_achievements_report
from bot.telegram.club_pairings import send_club_pairings
from bot.telegram.deck_reminder import send_deferred_deck_reminders
from bot.telegram.round_notify import send_round_notifications
from bot.tournament_creation import execute_due_creation_plans
from core import models
from core.clubs import club_identities, debug_club, default_clubs
from core.config import Club, ClubSchedule, settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.aetherhub_import_service import MIN_TOURNAMENT_DURATION, AetherhubImportService
from services.aetherhub_service import AetherhubService
from services.cellar import (
    CELLAR_CLUB_NAME,
    CELLAR_TIMEZONE,
    CellarService,
    cellar_notification_recipients,
    format_coordinator_summary,
)
from services.cellar_sheet import CellarCatalogSourceError, GoogleSheetsCellarCatalog
from services.datalens import DataLensService
from services.deck_mapping import refresh_archetype_macro
from services.deck_reminders import DeckReminderStage
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.magicoculus import (
    MagicOculusClient,
    MagicOculusImporter,
    MagicOculusImportResult,
    MagicOculusTournamentCollector,
)
from services.meta_police_message import MetaPoliceMessageService
from services.names import format_participant_name
from services.schedule import ScheduleService
from services.stats import StatsService
from services.tournament import MAX_ACTIVE_TOURNAMENTS_PER_CLUB, TournamentService

logger = logging.getLogger(__name__)

CELLAR_CATALOG_SYNC_TIME = "23:00"


@dataclass(frozen=True)
class AnnouncementDelivery:
    chat_id: int
    message_id: int | None


DAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _ptb_day(weekday: str) -> int:
    """Convert weekday string to PTB run_daily days= value (0=Sunday, 6=Saturday).

    PTB v20+ changed the convention from 0=Monday to 0=Sunday (cron-style).
    Python's datetime.weekday() uses 0=Monday. Conversion: ptb = (py + 1) % 7.
    """
    return (DAYS[weekday] + 1) % 7


def _create_run_weekday(schedule: ClubSchedule) -> int:
    """Python weekday on which the tournament creation job must run."""
    return (DAYS[schedule.weekday] - schedule.create_days_before) % 7


def _event_datetime(now: datetime, schedule: ClubSchedule) -> datetime:
    """Scheduled local start, even when registration opens on an earlier date."""
    event_date = now.date() + timedelta(days=schedule.create_days_before)
    game_time = datetime.strptime(schedule.game_time, "%H:%M").time()
    return datetime.combine(event_date, game_time, tzinfo=now.tzinfo)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _import_day_offset(import_times: list[str], fetch_time: str) -> int:
    """Return 1 for import times after a midnight rollover in the configured sequence."""
    previous_minutes: int | None = None
    day_offset = 0
    for current in import_times:
        hour, minute = (int(part) for part in current.split(":"))
        current_minutes = hour * 60 + minute
        if previous_minutes is not None and current_minutes < previous_minutes:
            day_offset = 1
        if current == fetch_time:
            return day_offset
        previous_minutes = current_minutes
    return 0


async def send_registration_open(bot, db, club: Club, tournament_id: int, base_text: str) -> None:
    await _send_registration_open(
        bot,
        db,
        club,
        tournament_id,
        base_text,
        owner_chat_id=settings.OWNER_CHAT_ID,
    )


# ---------------------------------------------------------------------------
# Club definitions
# ---------------------------------------------------------------------------


def get_clubs() -> list[Club]:
    """Клубы с расписанием из БД (issue #124/#125).

    Расписание — данные, а не код: строки лежат в `club_schedules` и правятся админом из
    `/schedule`. Если БД недоступна или таблица пуста (первый старт до `ensure_defaults`),
    возвращаем дефолты из кода — остаться совсем без расписания хуже, чем отработать по
    дефолтному. Отладочный клуб добавляется только при DEBUG и через БД не управляется.
    """
    clubs: list[Club] | None = None
    db = SessionLocal()
    try:
        rows = ScheduleService(db).list_rows()
        if rows:
            clubs = ScheduleService(db).build_clubs()
    except Exception:
        logger.exception("get_clubs: не смог прочитать расписание из БД — беру дефолты из кода")
    finally:
        db.close()

    if clubs is None:
        clubs = default_clubs()

    debug = debug_club()
    if debug is not None:
        clubs = [*clubs, debug]
    return clubs


# ---------------------------------------------------------------------------
# Job: create tournament
# ---------------------------------------------------------------------------


class CreateTournamentJob:
    """Creates the club's tournament on its configured registration-opening day."""

    def __init__(self, club: Club, schedule: ClubSchedule) -> None:
        self.club = club
        self.schedule = schedule

    async def run(self, bot, now: datetime, db=None) -> None:
        logger.info(f"CreateTournamentJob: running for '{self.club.name}', now={now.strftime('%A %H:%M')}")
        run_weekday = _create_run_weekday(self.schedule)
        if now.weekday() != run_weekday:
            logger.info(
                "CreateTournamentJob: skipping '%s' — expected weekday=%s (now=%s)",
                self.club.name,
                run_weekday,
                now.strftime("%A"),
            )
            return

        event_at = _event_datetime(now, self.schedule)
        date_str = event_at.strftime("%Y-%m-%d")
        title = f"{self.club.title_prefix}{self.club.name} Pauper {event_at.strftime('%d.%m.%Y')}"
        club_slug = "-".join(self.club.name.lower().split())
        slug = f"{date_str}-{club_slug}-pauper"

        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            svc = TournamentService(db)
            try:
                active = svc.list_active_tournaments_for_club(self.club.name)
                if len(active) >= MAX_ACTIVE_TOURNAMENTS_PER_CLUB:
                    logger.warning(
                        "CreateTournamentJob: skipping '%s' — active tournament limit reached (%s: %s)",
                        self.club.name,
                        len(active),
                        ", ".join(f"#{t.id}" for t in active),
                    )
                    return

                new_t = svc.create_tournament(
                    TournamentCreate(
                        title=title,
                        chat_id=self.club.chat_id or 0,
                        slug=slug,
                        club=self.club.name,
                        is_online=self.club.is_online,
                        registration_close_at=_naive_utc(event_at),
                    )
                )
                if self.club.name == CELLAR_CLUB_NAME and FeatureFlagService(db).is_enabled(FeatureFlags.CELLAR_DECKS):
                    try:
                        CellarService(db).attach_event_to_tournament(event_at.date(), new_t.id)
                    except Exception:
                        db.rollback()
                        logger.exception("CreateTournamentJob: cellar reservations failed for #%s", new_t.id)
                logger.info(f"Created tournament #{new_t.id} '{title}' for '{self.club.name}'")

                if bot is not None:
                    when = (
                        "сегодня"
                        if self.schedule.create_days_before == 0
                        else "завтра"
                        if self.schedule.create_days_before == 1
                        else event_at.strftime("%d.%m.%Y")
                    )
                    text = (
                        f"🏆 {self.club.name} Pauper — {when} в {self.schedule.game_time}\n"
                        f"Турнир создан. Регистрация открыта."
                    )
                    await send_registration_open(bot, db, self.club, new_t.id, text)
            except Exception as e:
                logger.error(f"CreateTournamentJob error for '{self.club.name}': {e}", exc_info=True)
        finally:
            if close_db:
                db.close()


class PreStartReminderJob:
    """Перед началом турнира напоминает игрокам записать колоду (кнопка-диплинк, issue #136)."""

    def __init__(self, club: Club, schedule: ClubSchedule) -> None:
        self.club = club
        self.schedule = schedule

    async def run(self, bot, now: datetime, db=None) -> None:
        if now.weekday() != DAYS[self.schedule.weekday]:
            return
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            active = TournamentService(db).get_active_tournament_for_club(self.club.name)
            if active is None:
                logger.info("PreStartReminderJob: no active tournament for '%s'", self.club.name)
                return
            text = (
                f"⏰ {self.club.name} Pauper начинается в {self.schedule.game_time}!\n"
                f"Ещё не записали колоду? Успейте — жмите кнопку ниже."
            )
            try:
                await send_registration_open(bot, db, self.club, active.id, text)
            except Exception:
                logger.exception("PreStartReminderJob: group reminder failed for #%s", active.id)
            try:
                await send_deferred_deck_reminders(
                    bot,
                    db,
                    active.id,
                    DeckReminderStage.PRESTART,
                )
            except Exception:
                logger.exception("PreStartReminderJob: deck reminders failed for #%s", active.id)
        except Exception:
            logger.exception("PreStartReminderJob error for '%s'", self.club.name)
        finally:
            if close_db:
                db.close()


class CellarCoordinatorReminderJob:
    """Send each configured coordinator one idempotent summary shortly before the event."""

    async def run(self, bot, now: datetime, db=None) -> None:
        if bot is None:
            return
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            if not FeatureFlagService(db).is_enabled(FeatureFlags.CELLAR_DECKS):
                return
            recipients = cellar_notification_recipients(db)
            if not recipients:
                return
            now_utc = _naive_utc(now)
            tournament = db.execute(
                select(models.Tournament)
                .where(
                    models.Tournament.club == CELLAR_CLUB_NAME,
                    models.Tournament.status == models.TournamentStatus.REGISTRATION,
                    models.Tournament.registration_close_at > now_utc,
                    models.Tournament.registration_close_at <= now_utc + timedelta(hours=1),
                )
                .order_by(models.Tournament.registration_close_at)
                .limit(1)
            ).scalar_one_or_none()
            if tournament is None:
                return
            event_at = tournament.registration_close_at.replace(tzinfo=timezone.utc).astimezone(CELLAR_TIMEZONE)
            service = CellarService(db)
            reservations = service.active_reservations(event_at.date())
            if not reservations:
                return
            text = format_coordinator_summary(event_at.date(), reservations)
            for recipient_tg_id in recipients:
                delivery = service.coordinator_delivery(event_at.date(), recipient_tg_id)
                if delivery.delivered_at is not None:
                    continue
                try:
                    await bot.send_message(chat_id=recipient_tg_id, text=text)
                except Exception as exc:  # noqa: BLE001 — retry on the next minute
                    service.finish_coordinator_delivery(delivery, error=str(exc))
                    logger.exception("Cellar coordinator reminder failed for %s", recipient_tg_id)
                    continue
                service.finish_coordinator_delivery(delivery)
        finally:
            if close_db:
                db.close()


class CellarCatalogSyncJob:
    """Refresh the public cellar sheet once a week without blocking the bot event loop."""

    def __init__(self, source: GoogleSheetsCellarCatalog | None = None) -> None:
        self._source = source or GoogleSheetsCellarCatalog()

    async def run(self, db=None) -> tuple[int, int, int] | None:
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            if not FeatureFlagService(db).is_enabled(FeatureFlags.CELLAR_DECKS):
                return None
            entries = await asyncio.to_thread(self._source.fetch)
            result = CellarService(db).sync_catalog(entries)
            logger.info(
                "Каталог колод из ячейки синхронизирован: created=%s updated=%s deactivated=%s",
                *result,
            )
            return result
        except CellarCatalogSourceError:
            logger.exception("Не удалось выполнить еженедельную синхронизацию каталога ячейки")
            return None
        finally:
            if close_db:
                db.close()


# ---------------------------------------------------------------------------
# Job: AetherHub auto-import
# ---------------------------------------------------------------------------


class AetherhubImportJob:
    """Fetches today's pauper tournament from AetherHub and imports it automatically."""

    def __init__(
        self,
        club: Club,
        schedule: ClubSchedule,
        aetherhub_service: AetherhubService | None = None,
        event_day_offset: int = 0,
        attempt_number: int = 1,
    ) -> None:
        self.club = club
        self.schedule = schedule
        self._aetherhub = aetherhub_service or AetherhubService()
        self._event_day_offset = event_day_offset
        self._attempt_number = attempt_number

    async def _notify_owner_not_found(self, bot, db, tournament: models.Tournament, event_date: date) -> None:
        """Send one owner-only DM after the second exact-date lookup misses the event."""
        if self._attempt_number != 2 or bot is None or tournament.aetherhub_not_found_notified_at is not None:
            return

        owner_chat_id = settings.OWNER_CHAT_ID
        allowed_ids = settings.notify_allowed_ids
        if not owner_chat_id or (allowed_ids is not None and owner_chat_id not in allowed_ids):
            return

        try:
            await bot.send_message(
                chat_id=owner_chat_id,
                text=format_tournament_not_found(self.club.aetherhub_url, event_date),
            )
            tournament.aetherhub_not_found_notified_at = models.utc_now()
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "AetherhubImportJob: failed to notify owner that no tournament was found for '%s'",
                self.club.name,
            )

    async def run(self, now: datetime, db=None, bot=None) -> None:
        logger.info(f"AetherhubImportJob: running for '{self.club.name}', now={now.strftime('%A %H:%M')}")
        if not self.club.aetherhub_url:
            logger.warning(f"AetherhubImportJob: no aetherhub_url for '{self.club.name}', skipping")
            return
        run_weekday = (DAYS[self.schedule.weekday] + self._event_day_offset) % 7
        if now.weekday() != run_weekday:
            logger.info(
                "AetherhubImportJob: skipping '%s' — expected weekday=%s (now=%s)",
                self.club.name,
                run_weekday,
                now.strftime("%A"),
            )
            return

        close_db = db is None
        if close_db:
            db = SessionLocal()

        url: str | None = None
        tournament_id: int | None = None
        auto_discovered = False

        try:
            tournament = _find_active_club_tournament(db, self.club.name)
            if not tournament:
                logger.warning(f"AetherhubImportJob: no active tournament for '{self.club.name}'")
                return

            tournament_id = tournament.id
            url = tournament.aetherhub_url

            if not url:
                logger.info(f"AetherhubImportJob: fetching club page for '{self.club.name}'")
                event_date = now.date() - timedelta(days=self._event_day_offset)
                today = None if self.schedule.find_latest else event_date
                try:
                    url = self._aetherhub.find_todays_pauper_tournament(self.club.aetherhub_url, today=today)
                except Exception:
                    logger.exception(f"AetherhubImportJob: failed to fetch club page for '{self.club.name}'")
                    return
                if not url:
                    logger.info(f"AetherhubImportJob: no pauper tournament found for '{self.club.name}'")
                    if today is not None:
                        await self._notify_owner_not_found(bot, db, tournament, event_date)
                    return
                auto_discovered = True

            logger.info(f"AetherhubImportJob: importing {url} for tournament #{tournament_id}")
            try:
                data = self._aetherhub.fetch_tournament(url)
            except Exception:
                logger.exception(f"AetherhubImportJob: failed to fetch tournament data from {url}")
                return

            if auto_discovered and not data.players:
                logger.info(
                    f"AetherhubImportJob: auto-discovered tournament {url} has no players; "
                    "skipping import and URL binding"
                )
                return

            try:
                result = AetherhubImportService(db).import_tournament(tournament_id, data)
                logger.info(
                    f"AetherhubImportJob done for '{self.club.name}' #{tournament_id}: "
                    f"registered={result.registered}, already={result.already_registered}, "
                    f"pairings={result.pairings_saved}, new_rounds={result.new_round_numbers}"
                )
            except Exception:
                logger.exception(f"AetherhubImportJob: import failed for '{self.club.name}'")
                return

            if result.new_round_numbers and bot is not None:
                try:
                    await send_club_pairings(bot, db, tournament_id, result.new_round_numbers)
                except Exception:
                    logger.exception(f"AetherhubImportJob: club pairing publication failed for #{tournament_id}")
                try:
                    await send_round_notifications(
                        bot, db, tournament_id, result.new_round_numbers, datalens_service=DataLensService()
                    )
                except Exception:
                    logger.exception(f"AetherhubImportJob: round notifications failed for #{tournament_id}")
            if 2 in result.new_round_numbers and bot is not None:
                try:
                    await send_deferred_deck_reminders(
                        bot,
                        db,
                        tournament_id,
                        DeckReminderStage.ROUND2,
                    )
                except Exception:
                    logger.exception(f"AetherhubImportJob: deck reminders failed for #{tournament_id}")

            if tournament.aetherhub_url != url:
                db_url = SessionLocal()
                try:
                    TournamentService(db_url).set_aetherhub_url(tournament_id, url)
                except Exception:
                    logger.exception(f"AetherhubImportJob: failed to save aetherhub_url for #{tournament_id}")
                    return
                finally:
                    db_url.close()

            db_completion = SessionLocal()
            try:
                await maybe_announce_meta_gather_completed(bot, db_completion, tournament_id)
            except Exception:
                logger.exception(f"AetherhubImportJob: completion announce failed for #{tournament_id}")
            finally:
                db_completion.close()
        finally:
            if close_db:
                db.close()


# ---------------------------------------------------------------------------
# Job: per-tournament timed import (set via admin button)
# ---------------------------------------------------------------------------


class AetherhubTimedImportJob:
    """Runs every minute; triggers import for tournaments with matching aetherhub_import_time."""

    def __init__(self, aetherhub_service: AetherhubService) -> None:
        self._aetherhub = aetherhub_service

    async def run(self, now: datetime, db=None, bot=None) -> None:
        current_time = now.strftime("%H:%M")
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            stmt = select(models.Tournament).where(
                models.Tournament.aetherhub_import_time == current_time,
                models.Tournament.status != models.TournamentStatus.CLOSED,
            )
            tournaments = db.execute(stmt).scalars().all()
        finally:
            if close_db:
                db.close()

        if not tournaments:
            logger.debug(f"AetherhubTimedImportJob: no tournaments scheduled for {current_time}")
            return

        logger.info(f"AetherhubTimedImportJob: found {len(tournaments)} tournament(s) for {current_time}")

        club_url_map = {c.name: c.aetherhub_url for c in get_clubs() if c.aetherhub_url}
        today = None if settings.DEBUG else now.date()

        for t in tournaments:
            await self._import_tournament(t.id, t.aetherhub_url, t.club, club_url_map, today, bot=bot)

    async def _import_tournament(
        self,
        tournament_id: int,
        stored_url: str | None,
        club_name: str | None,
        club_url_map: dict,
        today,
        bot=None,
    ) -> None:
        url = stored_url
        if not url:
            club_page_url = club_url_map.get(club_name or "")
            if not club_page_url:
                logger.warning(f"AetherhubTimedImportJob: no club URL for tournament #{tournament_id}")
                return
            try:
                url = self._aetherhub.find_todays_pauper_tournament(club_page_url, today=today)
            except Exception:
                logger.exception(f"AetherhubTimedImportJob: failed to fetch club page for #{tournament_id}")
                return
            if not url:
                logger.info(f"AetherhubTimedImportJob: no pauper tournament found for #{tournament_id}")
                return

        logger.info(f"AetherhubTimedImportJob: importing {url} for tournament #{tournament_id}")
        db = SessionLocal()
        try:
            try:
                data = self._aetherhub.fetch_tournament(url)
            except Exception:
                logger.exception(f"AetherhubTimedImportJob: failed to fetch data from {url}")
                return
            try:
                result = AetherhubImportService(db).import_tournament(tournament_id, data)
                logger.info(
                    f"AetherhubTimedImportJob done #{tournament_id}: "
                    f"registered={result.registered}, pairings={result.pairings_saved}, "
                    f"new_rounds={result.new_round_numbers}"
                )
            except Exception:
                logger.exception(f"AetherhubTimedImportJob: import failed for #{tournament_id}")
                return

            if result.new_round_numbers and bot is not None:
                try:
                    await send_club_pairings(bot, db, tournament_id, result.new_round_numbers)
                except Exception:
                    logger.exception(f"AetherhubTimedImportJob: club pairing publication failed for #{tournament_id}")
                try:
                    await send_round_notifications(
                        bot, db, tournament_id, result.new_round_numbers, datalens_service=DataLensService()
                    )
                except Exception:
                    logger.exception(f"AetherhubTimedImportJob: round notifications failed for #{tournament_id}")
            if 2 in result.new_round_numbers and bot is not None:
                try:
                    await send_deferred_deck_reminders(
                        bot,
                        db,
                        tournament_id,
                        DeckReminderStage.ROUND2,
                    )
                except Exception:
                    logger.exception(f"AetherhubTimedImportJob: deck reminders failed for #{tournament_id}")

            try:
                await maybe_announce_meta_gather_completed(bot, db, tournament_id)
            except Exception:
                logger.exception(f"AetherhubTimedImportJob: completion announce failed for #{tournament_id}")
        finally:
            db.close()

        db2 = SessionLocal()
        try:
            TournamentService(db2).set_aetherhub_url(tournament_id, url)
        except Exception:
            logger.exception(f"AetherhubTimedImportJob: failed to save aetherhub_url for #{tournament_id}")
        finally:
            db2.close()


FINAL_REIMPORT_TIMES = ("09:00", "12:00", "18:00")
FINAL_REIMPORT_WINDOW_DAYS = 2  # окно «недавних» турниров для повторного импорта


class AetherhubFinalReimportJob:
    """Несколько раз в сутки перезатягивает незавершённые турниры с AetherHub.

    Счёт матчей на AetherHub публично появляется только ПОСЛЕ завершения турнира
    (формат страницы меняется js → edinorog, см. docs/aetherhub_formats.md). Импорт
    во время игры счёта не видит, поэтому утром следующего дня перезатягиваем
    паринги уже завершившихся турниров. Без уведомлений — это только добор счёта.
    """

    def __init__(self, aetherhub_service: AetherhubService) -> None:
        self._aetherhub = aetherhub_service

    async def run(self, now: datetime, db=None, bot=None) -> None:
        now_utc = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
        cutoff = now_utc - timedelta(days=FINAL_REIMPORT_WINDOW_DAYS)
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            stmt = select(models.Tournament).where(
                models.Tournament.aetherhub_url.isnot(None),
                models.Tournament.created_at >= cutoff,
                models.Tournament.status != models.TournamentStatus.CLOSED,
                models.Tournament.completed_announced_at.is_(None),
            )
            tournaments = db.execute(stmt).scalars().all()
        finally:
            if close_db:
                db.close()

        if not tournaments:
            logger.info("AetherhubFinalReimportJob: no recent tournaments to re-import")
            return
        logger.info("AetherhubFinalReimportJob: re-importing %d tournament(s) for final scores", len(tournaments))
        for t in tournaments:
            await self._reimport(t.id, t.aetherhub_url, bot=bot)

    async def _reimport(self, tournament_id: int, url: str, bot=None) -> None:
        try:
            data = self._aetherhub.fetch_tournament(url)
        except Exception:
            logger.exception("AetherhubFinalReimportJob: fetch failed for #%s (%s)", tournament_id, url)
            return
        db = SessionLocal()
        try:
            result = AetherhubImportService(db).import_tournament(tournament_id, data)
            logger.info("AetherhubFinalReimportJob done #%s: pairings_saved=%s", tournament_id, result.pairings_saved)
            # Финальный счёт обычно появляется именно здесь (утро после турнира) →
            # это типичный момент срабатывания анонса о завершении сбора метагейма.
            try:
                await maybe_announce_meta_gather_completed(bot, db, tournament_id)
            except Exception:
                logger.exception("AetherhubFinalReimportJob: completion announce failed for #%s", tournament_id)
        except Exception:
            logger.exception("AetherhubFinalReimportJob: import failed for #%s", tournament_id)
        finally:
            db.close()


REVEAL_DECKS_TIME = "22:00"  # авто-раскрытие колод турниров текущего дня
UNCLOSED_REMINDER_TIME = "10:00"
MISSING_DECKS_REMINDER_TIME = "15:00"


class AutoRevealDecksJob:
    """Раз в сутки в REVEAL_DECKS_TIME раскрывает колоды активных турниров этого дня.

    Во время регистрации колоды скрыты (``decks_hidden=True``), чтобы их не копировали.
    Раньше админ раскрывал их кнопкой «Показать колоды»; теперь это происходит
    автоматически вечером. Для плановых турниров ждём их ``registration_close_at``;
    legacy/ручные турниры без этого поля раскрываем в день создания.
    """

    async def run(self, now: datetime, db=None, bot=None) -> None:
        now_utc = _naive_utc(now)
        if now.tzinfo:
            day_start = (
                now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
            )
        else:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            stmt = select(models.Tournament).where(
                models.Tournament.status != models.TournamentStatus.CLOSED,
                models.Tournament.decks_hidden.is_(True),
                or_(
                    models.Tournament.registration_close_at <= now_utc,
                    and_(
                        models.Tournament.registration_close_at.is_(None),
                        models.Tournament.created_at >= day_start,
                    ),
                ),
            )
            tournaments = db.execute(stmt).scalars().all()
            if not tournaments:
                logger.info("AutoRevealDecksJob: no tournaments with hidden decks to reveal")
                return
            svc = TournamentService(db)
            for t in tournaments:
                svc.set_decks_hidden(t.id, hidden=False)
            logger.info(
                "AutoRevealDecksJob: revealed decks for %d tournament(s): %s",
                len(tournaments),
                [t.id for t in tournaments],
            )
            if bot is not None:
                for t in tournaments:
                    await self._announce(bot, db, t)
        finally:
            if close_db:
                db.close()

    async def _announce(self, bot, db, tournament) -> None:
        """Анонс «колоды раскрыты» + короткая мета (топ колод) в личку владельца.

        Пока шлём владельцу (`settings.OWNER_CHAT_ID`), а не в чат турнира — и в debug,
        и в prod. Позже можно переключить на чат клуба, поменяв адресата здесь.
        """
        if not settings.OWNER_CHAT_ID:
            return
        total = len(TournamentService(db).list_participants_for_tournament(tournament.id))
        meta = StatsService(db).get_tournament_meta(tournament.id)
        with_deck = sum(row.count for row in meta)
        text = format_decks_revealed(tournament.title, total, with_deck, meta)
        try:
            await bot.send_message(chat_id=settings.OWNER_CHAT_ID, text=text)
        except Exception:  # noqa: BLE001 — сбой одного анонса не должен ронять джобу
            logger.exception("AutoRevealDecksJob: announce failed for #%s", tournament.id)


class UnclosedTournamentReminderJob:
    """Owner-only напоминания о незакрытых турнирах через 3 и 7 суток."""

    async def run(self, bot, now: datetime, db=None) -> None:
        if bot is None or not settings.OWNER_CHAT_ID:
            return
        now_utc = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            tournaments = (
                db.execute(select(models.Tournament).where(models.Tournament.status != models.TournamentStatus.CLOSED))
                .scalars()
                .all()
            )
            for tournament in tournaments:
                age = now_utc - tournament.created_at
                days: int | None = None
                if age >= timedelta(days=7) and tournament.unclosed_reminder_7d_sent_at is None:
                    days = 7
                elif age >= timedelta(days=3) and tournament.unclosed_reminder_3d_sent_at is None:
                    days = 3
                if days is None:
                    continue

                participants = TournamentService(db).list_participants_for_tournament(tournament.id)
                with_deck = sum(participant.archetype_id is not None for participant in participants)
                day_word = "дня" if days == 3 else "дней"
                text = (
                    f"⚠️ Турнир не закрыт уже {days} {day_word}\n\n"
                    f"{tournament.title}\n"
                    f"Участников: {len(participants)} ({with_deck} с колодой)\n"
                    f"ID турнира: {tournament.id}\n\n"
                    "Проверь данные и закрой турнир, когда он будет готов."
                )
                try:
                    await bot.send_message(chat_id=settings.OWNER_CHAT_ID, text=text)
                except Exception:  # noqa: BLE001 — повторим на следующем ежедневном запуске
                    logger.exception(
                        "UnclosedTournamentReminderJob: %s-day reminder failed for #%s", days, tournament.id
                    )
                    continue

                sent_at = models.utc_now()
                if days == 7:
                    tournament.unclosed_reminder_7d_sent_at = sent_at
                    tournament.unclosed_reminder_3d_sent_at = tournament.unclosed_reminder_3d_sent_at or sent_at
                else:
                    tournament.unclosed_reminder_3d_sent_at = sent_at
                db.commit()
        finally:
            if close_db:
                db.close()


class MissingDecksReminderJob:
    """Один раз просит чат заполнить колоды на следующий календарный день после турнира."""

    @staticmethod
    def _event_date(tournament, tz) -> date:
        event_at = tournament.registration_close_at or tournament.started_at or tournament.created_at
        if event_at.tzinfo is None:
            event_at = event_at.replace(tzinfo=timezone.utc)
        return event_at.astimezone(tz).date()

    async def run(self, bot, now: datetime, db=None) -> None:
        if bot is None:
            return
        tz = now.tzinfo or ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            tournaments = (
                db.execute(
                    select(models.Tournament).where(
                        models.Tournament.status != models.TournamentStatus.CLOSED,
                        models.Tournament.missing_decks_reminder_1d_sent_at.is_(None),
                    )
                )
                .scalars()
                .all()
            )
            for tournament in tournaments:
                elapsed_days = (local_now.date() - self._event_date(tournament, tz)).days
                if elapsed_days < 1:
                    continue

                participants = TournamentService(db).list_participants_for_tournament(tournament.id)
                missing_participants = [participant for participant in participants if participant.archetype_id is None]
                if not missing_participants:
                    continue

                try:
                    me = await bot.get_me()
                    community_fill_enabled = FeatureFlagService(db).is_enabled(FeatureFlags.RECORD_OPPONENTS)
                    button_url = (
                        fill_missing_deeplink(me.username, tournament.id)
                        if community_fill_enabled
                        else registration_deeplink(me.username, tournament.id)
                    )
                except Exception:  # noqa: BLE001 — без рабочей кнопки уведомление не считаем доставленным
                    logger.exception("MissingDecksReminderJob: get_me failed for #%s", tournament.id)
                    continue

                text = format_missing_decks_reminder(
                    tournament.title,
                    missing_participants,
                    community_fill_enabled=community_fill_enabled,
                )
                button_text = "Записать" if community_fill_enabled else "Записаться"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(button_text, url=button_url)]])
                try:
                    message = await bot.send_message(
                        chat_id=tournament.chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                except Exception:  # noqa: BLE001 — повторим на следующем ежедневном запуске
                    logger.exception("MissingDecksReminderJob: reminder failed for #%s", tournament.id)
                    continue

                tournament.missing_decks_reminder_1d_sent_at = models.utc_now()
                db.commit()
                message_id = getattr(message, "message_id", None)
                if community_fill_enabled and isinstance(message_id, int):
                    try:
                        MetaPoliceMessageService(db).upsert(
                            tournament_id=tournament.id,
                            chat_id=tournament.chat_id,
                            message_id=message_id,
                            participant_ids=[participant.id for participant in missing_participants],
                            button_url=button_url,
                        )
                    except Exception:  # noqa: BLE001 — сообщение уже доставлено, повторно не шлём
                        db.rollback()
                        logger.exception("MissingDecksReminderJob: tracking failed for #%s", tournament.id)
        finally:
            if close_db:
                db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def maybe_announce_meta_gather_completed(bot, db, tournament_id: int, chart_svc=None) -> None:
    """Один раз анонсирует «сбор метагейма завершён» с графиком и стендингами.

    Срабатывает после импорта ИЛИ после записи колоды при выполнении ВСЕХ условий:
    - турнир привязан к AetherHub (``aetherhub_url``) — только настоящие турниры;
    - прошло ≥ ``MIN_TOURNAMENT_DURATION`` с начала игры (``started_at``) — иначе счёт
      раннего раунда мог бы преждевременно сойти за завершённость;
    - у всех не-бай матчей есть счёт (``is_tournament_complete``);
    - у всех участников заполнена колода (``_all_decks_filled``) — метагейм собран.

    Идемпотентность — флаг ``Tournament.completed_announced_at``, который **занимается до
    отправки** атомарным ``UPDATE ... WHERE completed_announced_at IS NULL``. Раньше он
    ставился после отправки, и это приводило к дублям на следующий день: между проверкой и
    записью флага код несколько раз уходит в await (рисование картинок, отправка альбома), а
    сессия у бота одна на поток (``scoped_session``) — соседняя задача успевала её закрыть,
    и присваивание атрибута коммитилось «в никуда». Отбивка ушла, флаг пуст, утренний
    реимпорт честно повторял анонс.

    Если доставить не удалось НИ в один чат — бронь снимаем, и анонс повторится на следующем
    импорте (в т.ч. ночной 09:00-реимпорт — гарантированный бэкап, там >3ч всегда).

    Шлём в чат клуба (``tournament.chat_id``, где создан турнир) И владельцу в личку
    (``settings.OWNER_CHAT_ID``), дедуплицированно. Плюс благодарим метаписцев, записавших
    ≥2 колод.

    ``chart_svc`` — шов для тестов, чтобы они не поднимали сервис из глобального конфига.
    """
    if bot is None:
        return
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None or tournament.completed_announced_at is not None:
        return

    # Только для «настоящих» турниров, привязанных к AetherHub: у отладочных/ручных нет
    # aetherhub_url, и их завершённость по счёту матчей неопределена.
    if not tournament.aetherhub_url:
        return

    # Минимальная длительность турнира — 3 часа. Раньше «сбор завершён» быть не может:
    # это отсекает преждевременный анонс, когда AetherHub уже проставил счёт раннего раунда,
    # но следующие ещё не сыграны. started_at ≈ старт игры (первый импорт раунда).
    if tournament.started_at is None:
        return
    if models.utc_now() - tournament.started_at < MIN_TOURNAMENT_DURATION:
        return

    svc = AetherhubImportService(db)
    if not svc.is_tournament_complete(tournament_id):
        return

    # Метагейм собран только когда у ВСЕХ участников заполнена колода — неважно кем (сам
    # записался или дописали через «запись оппонентов»). Пока хоть у одного пусто — ждём.
    if not _all_decks_filled(db, tournament_id):
        return

    # Адресаты отбивки: чат клуба (где создан турнир) и владелец в личку — дедуплицированно.
    targets = list(dict.fromkeys(cid for cid in (tournament.chat_id, settings.OWNER_CHAT_ID) if cid))
    if not targets:
        return
    title = tournament.title  # читаем ДО отправки: за await объект может стать detached

    # 1) Занимаем право на анонс ДО отправки — одним атомарным UPDATE ... WHERE ... IS NULL.
    if not _reserve_announce(db, tournament_id):
        return

    try:
        deliveries = await _announce_to_targets(bot, db, tournament_id, title, targets, svc, chart_svc)
    except Exception:
        _release_announce(db, tournament_id)  # непредвиденный сбой — пусть повторится позже
        raise
    # 2) Ни один адресат не получил — снимаем бронь, чтобы анонс повторился на следующем импорте.
    if not deliveries:
        _release_announce(db, tournament_id)
        return
    # 3) турнир завершён — закрываем (REGISTRATION → CLOSED). Best-effort: сбой закрытия не должен
    #    ронять уже доставленный анонс; флаг уже стоит, повтора анонса не будет.
    try:
        TournamentService(db).close_tournament(tournament_id)
    except Exception:
        logger.exception("maybe_announce_meta_gather_completed: close failed for #%s", tournament_id)
    # 4) ачивки: турнир завершён и полон — считаем и шлём отчёт владельцу (теневой режим).
    #    Best-effort: движок ачивок не должен ронять уже доставленный анонс.
    try:
        await send_achievements_report(bot, db, tournament_id)
    except Exception:
        logger.exception("maybe_announce_meta_gather_completed: achievements failed for #%s", tournament_id)
    # 5) Magic Oculus: отдельная сессия и worker thread, чтобы HTTP не блокировал Telegram loop.
    #    Флаг управляемый; ошибка внешнего API не откатывает закрытый турнир.
    if FeatureFlagService(db).is_enabled(FeatureFlags.MAGIC_OCULUS_IMPORT):
        try:
            oculus_result = await asyncio.to_thread(import_closed_tournament_to_magicoculus, tournament_id)
        except Exception as exc:
            logger.exception("maybe_announce_meta_gather_completed: Magic Oculus import failed for #%s", tournament_id)
            await _notify_magicoculus_import_error(bot, tournament_id, title, exc)
        else:
            await _send_magicoculus_success_link(
                bot,
                tournament.chat_id,
                title,
                oculus_result.tournament_id,
            )
    logger.info("maybe_announce_meta_gather_completed: announced completion for #%s", tournament_id)


def import_closed_tournament_to_magicoculus(tournament_id: int) -> MagicOculusImportResult:
    """Синхронный worker: собрать, проверить и one-shot импортировать закрытый турнир."""
    db = SessionLocal()
    try:
        tournament = MagicOculusTournamentCollector(db).collect(tournament_id, validate_aetherhub=True)
        identity = next(
            (row for row in club_identities() if row.name.casefold() == tournament.club.casefold()),
            None,
        )
        if identity is None or not identity.magicoculus_city:
            raise ValueError(f'Для клуба "{tournament.club}" не настроен город Magic Oculus')
        client = MagicOculusClient(settings.MAGIC_OCULUS_API_URL)
        return MagicOculusImporter(db, client).import_once(tournament, city=identity.magicoculus_city)
    finally:
        db.close()


async def _send_magicoculus_success_link(
    bot,
    chat_id: int | None,
    title: str,
    magicoculus_tournament_id: int,
) -> None:
    """Send one public Oculus link to the tournament's club chat after a successful import."""
    if bot is None or not chat_id:
        return
    url = f"{settings.MAGIC_OCULUS_PUBLIC_URL.rstrip('/')}/tournaments/{magicoculus_tournament_id}"
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Турнир загружен в Magic Oculus\n\n{title}\n{url}",
        )
    except Exception:  # noqa: BLE001 — уведомление не должно откатывать успешный импорт
        logger.exception(
            "maybe_announce_meta_gather_completed: Magic Oculus success link failed for #%s",
            magicoculus_tournament_id,
        )


async def _notify_magicoculus_import_error(bot, tournament_id: int, title: str, exc: Exception) -> None:
    """Best-effort DM владельцу; никогда не рассылает ошибку участникам или в клуб."""
    if bot is None or not settings.OWNER_CHAT_ID:
        return
    error = f"{type(exc).__name__}: {exc}".strip()
    # Telegram ограничивает сообщение 4096 символами; оставляем запас под заголовок.
    error = error[:3500]
    text = (
        f"⚠️ Не удалось загрузить турнир в Magic Oculus\n\nТурнир: {title}\nID в боте: #{tournament_id}\nОшибка: {error}"
    )
    try:
        await bot.send_message(chat_id=settings.OWNER_CHAT_ID, text=text)
    except Exception:  # noqa: BLE001 — Telegram не должен откатывать уже закрытый турнир
        logger.exception(
            "maybe_announce_meta_gather_completed: Magic Oculus error DM failed for #%s",
            tournament_id,
        )


def _reserve_announce(db, tournament_id: int) -> bool:
    """Атомарно занять право на анонс. True — заняли мы, False — уже занято кем-то.

    Одним `UPDATE ... WHERE completed_announced_at IS NULL`, а не мутацией ORM-объекта:
    это переживает и параллельный вызов из соседней джобы, и закрытие общей сессии
    (см. docstring `maybe_announce_meta_gather_completed`).
    """
    result = db.execute(
        update(models.Tournament)
        .where(
            models.Tournament.id == tournament_id,
            models.Tournament.completed_announced_at.is_(None),
        )
        .values(completed_announced_at=models.utc_now())
    )
    db.commit()
    return bool(result.rowcount)


def _release_announce(db, tournament_id: int) -> None:
    """Снять бронь: анонс не доставлен, пусть повторится на следующем импорте."""
    db.execute(
        update(models.Tournament).where(models.Tournament.id == tournament_id).values(completed_announced_at=None)
    )
    db.commit()
    logger.info("maybe_announce_meta_gather_completed: released reservation for #%s", tournament_id)


async def _announce_to_targets(
    bot, db, tournament_id: int, title: str, targets: list, svc, chart_svc
) -> list[AnnouncementDelivery]:
    """Собрать отбивку и вернуть Telegram IDs доставленных основных сообщений.

    В каждый чат — одно сообщение-альбом (картинки + текст подписью к первой); не вошедшие в
    альбом картинки — best-effort. Сбой одного адресата не мешает остальным.
    """
    macro_report = _refresh_and_format_macro_report(db, tournament_id)
    chart = await build_chart(db, tournament_id, chart_svc)
    standings = await build_standings(db, tournament_id)
    total = len(TournamentService(db).list_participants_for_tournament(tournament_id))
    with_deck = sum(s.count for s in chart.sectors) if chart else _decks_count(db, tournament_id)
    undefeated = svc.get_undefeated_players(tournament_id)
    scorekeepers = TournamentService(db).get_deck_recorders(tournament_id, min_count=2)
    text = format_meta_gather_completed(title, total, with_deck, undefeated, scorekeepers)
    no_show_names = _aetherhub_no_show_names(db, tournament_id)
    images = ([chart] if chart else []) + list(standings)

    deliveries: list[AnnouncementDelivery] = []
    for chat_id in targets:
        target_text = text
        if chat_id == settings.OWNER_CHAT_ID and no_show_names:
            names = "\n".join(f"• {name}" for name in no_show_names)
            target_text += (
                f"\n\n⚠️ Зарегистрировались в боте, но отсутствуют "
                f"в итоговых стендингах AetherHub ({len(no_show_names)}):\n{names}"
            )
        if chat_id == settings.OWNER_CHAT_ID and macro_report:
            target_text += f"\n\n{macro_report}"
        try:
            leftover, message_id = await _send_announce(bot, chat_id, target_text, images)
        except Exception:
            logger.exception(
                "maybe_announce_meta_gather_completed: announce to %s failed for #%s", chat_id, tournament_id
            )
            continue
        deliveries.append(AnnouncementDelivery(chat_id=chat_id, message_id=message_id))
        await _send_announce_images(bot, chat_id, leftover)
    return deliveries


def _refresh_and_format_macro_report(db, tournament_id: int) -> str:
    """Пересчитать классификацию и собрать экспериментальный owner-only срез."""
    rows = db.execute(
        select(models.Archetype, models.Participant.id)
        .join(models.Participant, models.Participant.archetype_id == models.Archetype.id)
        .where(models.Participant.tournament_id == tournament_id)
        .order_by(models.Participant.id)
    ).all()
    changed = False
    macro_counts: Counter[str] = Counter()
    sources: dict[str, Counter[str]] = defaultdict(Counter)
    unmapped = 0
    for archetype, _participant_id in rows:
        changed = refresh_archetype_macro(archetype) or changed
        if archetype.macro_name:
            macro_counts[archetype.macro_name] += 1
            sources[archetype.macro_name][archetype.general_name or archetype.name] += 1
        else:
            unmapped += 1
    if changed:
        db.commit()
    if not rows:
        return ""

    lines = ["🧪 Крупные архетипы (тест, только owner):"]
    for macro, count in sorted(macro_counts.items(), key=lambda item: (-item[1], item[0].casefold())):
        details = ", ".join(
            f"{name} ×{source_count}"
            for name, source_count in sorted(sources[macro].items(), key=lambda item: (-item[1], item[0].casefold()))
        )
        lines.append(f"• {macro} — {count} ({details})")
    if unmapped:
        lines.append(f"• Пока без крупной группы — {unmapped}")
    return "\n".join(lines)


def _aetherhub_no_show_names(db, tournament_id: int) -> list[str]:
    """Players registered in the bot but absent from published AetherHub standings.

    ``final_place`` is assigned from standings during AetherHub import. We only report missing
    places when at least one participant has a place, so a temporarily absent standings response
    never labels the whole tournament as no-shows.
    """
    participants = (
        db.execute(
            select(models.Participant)
            .where(models.Participant.tournament_id == tournament_id)
            .order_by(models.Participant.id)
        )
        .scalars()
        .all()
    )
    if not any(participant.final_place is not None for participant in participants):
        return []
    names = {
        format_participant_name(participant.user.first_name, participant.user.last_name).strip()
        for participant in participants
        if participant.final_place is None
    }
    return sorted((name for name in names if name), key=str.casefold)


def _decks_count(db, tournament_id: int) -> int:
    """Сколько участников с колодой. Нужен, только если график не построился."""
    return sum(row.count for row in StatsService(db).get_tournament_meta(tournament_id))


def _all_decks_filled(db, tournament_id: int) -> bool:
    """True, если есть участники и у ВСЕХ проставлена колода (archetype_id)."""
    archetype_ids = (
        db.execute(select(models.Participant.archetype_id).where(models.Participant.tournament_id == tournament_id))
        .scalars()
        .all()
    )
    return bool(archetype_ids) and all(aid is not None for aid in archetype_ids)


_TG_CAPTION_LIMIT = 1024  # максимум символов в подписи к медиа
_TG_ALBUM_LIMIT = 10  # максимум элементов в media group


async def _send_announce(bot, chat_id: int, text: str, images: list) -> tuple[list, int | None]:
    """Отправить отбивку в один чат одним сообщением: картинки альбомом, текст — подписью к первой.

    Возвращает остаток картинок и ID основного сообщения, к которому можно добавить кнопку.
    Если картинок нет или текст длиннее подписи — шлём текст отдельным сообщением и возвращаем
    все картинки как «остаток». Сбой альбома → фолбэк на текст (анонс важнее картинок).
    """
    if not images or len(text) > _TG_CAPTION_LIMIT:
        message = await bot.send_message(chat_id=chat_id, text=text)
        message_id = getattr(message, "message_id", None)
        return images, message_id if isinstance(message_id, int) else None

    album = images[:_TG_ALBUM_LIMIT]
    media = [InputMediaPhoto(io.BytesIO(img.png), caption=text if i == 0 else None) for i, img in enumerate(album)]
    try:
        messages = await bot.send_media_group(chat_id=chat_id, media=media)
    except Exception:
        logger.exception("maybe_announce_meta_gather_completed: media group failed — шлём текстом")
        message = await bot.send_message(chat_id=chat_id, text=text)
        message_id = getattr(message, "message_id", None)
        return images, message_id if isinstance(message_id, int) else None
    first_message = messages[0] if messages else None
    message_id = getattr(first_message, "message_id", None)
    return images[_TG_ALBUM_LIMIT:], message_id if isinstance(message_id, int) else None


async def _send_announce_images(bot, chat_id: int, images: list) -> None:
    """Best-effort отправка картинок анонса. Ловим любую ошибку — картинки не критичны."""
    for image in images:
        try:
            await bot.send_photo(chat_id=chat_id, photo=io.BytesIO(image.png))
        except Exception:
            logger.exception("maybe_announce_meta_gather_completed: image upload failed (%s)", image.filename)


def _find_active_club_tournament(db, club_name: str):
    """Find the current non-CLOSED tournament for a club."""
    stmt = (
        select(models.Tournament)
        .where(
            models.Tournament.club == club_name,
            models.Tournament.status != models.TournamentStatus.CLOSED,
        )
        .order_by(models.Tournament.created_at.desc(), models.Tournament.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


"""Префиксы имён джоб, которые строятся из расписания клубов.

Только эти джобы снимаются и вешаются заново при правке расписания в UI
(`reload_schedule_jobs`). Глобальные джобы (таймер импорта, ночной реимпорт,
авто-раскрытие колод) расписанием не управляются и живут до перезапуска бота.
"""
SCHEDULE_JOB_PREFIXES = ("create_tournament[", "prestart_reminder[", "aetherhub_import[")


def reload_schedule_jobs(app: Application) -> int:
    """Перевешивает джобы расписания по текущему состоянию БД. Возвращает число снятых джоб.

    Зовём после каждой правки расписания в `/schedule`, чтобы изменение применялось сразу,
    без перезапуска бота.
    """
    removed = 0
    for job in list(app.job_queue.jobs()):
        if job.name and job.name.startswith(SCHEDULE_JOB_PREFIXES):
            job.schedule_removal()
            removed += 1
    _register_schedule_jobs(app)
    logger.info("Scheduler: расписание перечитано — снято %s джоб, зарегистрированы заново", removed)
    return removed


def setup_scheduler(app: Application) -> None:
    """Registers daily jobs for each club and schedule."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)

    _register_schedule_jobs(app)

    timed_job = AetherhubTimedImportJob(AetherhubService())

    async def _timed_import(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await timed_job.run(now=datetime.now(tz_), bot=context.bot)

    app.job_queue.run_repeating(_timed_import, interval=60, first=10)
    logger.info("Scheduler: AetherhubTimedImportJob registered (every 60s)")

    async def _create_manually_scheduled_tournaments(context: ContextTypes.DEFAULT_TYPE) -> None:
        db = SessionLocal()
        try:
            await execute_due_creation_plans(context.bot, db)
        finally:
            db.close()

    _create_manually_scheduled_tournaments.__name__ = "manual_tournament_creation"
    app.job_queue.run_repeating(_create_manually_scheduled_tournaments, interval=60, first=15)
    logger.info("Scheduler: manual tournament creation registered (every 60s)")

    registration_refresh_job = RegistrationMessageRefreshJob()

    async def _refresh_registration_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
        await registration_refresh_job.run(context.bot)

    _refresh_registration_messages.__name__ = "registration_message_refresh"
    app.job_queue.run_repeating(_refresh_registration_messages, interval=60, first=60)
    logger.info("Scheduler: RegistrationMessageRefreshJob registered (every 60s)")

    cellar_reminder_job = CellarCoordinatorReminderJob()

    async def _remind_cellar_coordinators(context: ContextTypes.DEFAULT_TYPE) -> None:
        await cellar_reminder_job.run(context.bot, now=datetime.now(timezone.utc))

    _remind_cellar_coordinators.__name__ = "cellar_coordinator_reminder"
    app.job_queue.run_repeating(_remind_cellar_coordinators, interval=60, first=20)
    logger.info("Scheduler: CellarCoordinatorReminderJob registered (every 60s)")

    final_job = AetherhubFinalReimportJob(AetherhubService())

    def _make_final_reimport(time_str: str):
        async def _final_reimport(context: ContextTypes.DEFAULT_TYPE) -> None:
            tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
            await final_job.run(now=datetime.now(tz_), bot=context.bot)

        _final_reimport.__name__ = f"aetherhub_final_reimport[{time_str}]"
        return _final_reimport

    for time_str in FINAL_REIMPORT_TIMES:
        final_time = datetime.strptime(time_str, "%H:%M").time().replace(tzinfo=tz)
        app.job_queue.run_daily(_make_final_reimport(time_str), time=final_time)
    logger.info("Scheduler: AetherhubFinalReimportJob registered (daily %s)", ", ".join(FINAL_REIMPORT_TIMES))

    reveal_job = AutoRevealDecksJob()
    reveal_time = datetime.strptime(REVEAL_DECKS_TIME, "%H:%M").time().replace(tzinfo=tz)

    async def _reveal_decks(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await reveal_job.run(now=datetime.now(tz_), bot=context.bot)

    _reveal_decks.__name__ = "auto_reveal_decks"
    app.job_queue.run_daily(_reveal_decks, time=reveal_time)
    logger.info(f"Scheduler: AutoRevealDecksJob registered (daily {REVEAL_DECKS_TIME})")

    unclosed_reminder_job = UnclosedTournamentReminderJob()
    unclosed_reminder_time = datetime.strptime(UNCLOSED_REMINDER_TIME, "%H:%M").time().replace(tzinfo=tz)

    async def _remind_unclosed_tournaments(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await unclosed_reminder_job.run(context.bot, now=datetime.now(tz_))

    _remind_unclosed_tournaments.__name__ = "unclosed_tournament_reminders"
    app.job_queue.run_daily(_remind_unclosed_tournaments, time=unclosed_reminder_time)
    logger.info(f"Scheduler: UnclosedTournamentReminderJob registered (daily {UNCLOSED_REMINDER_TIME})")

    missing_decks_reminder_job = MissingDecksReminderJob()
    missing_decks_reminder_time = datetime.strptime(MISSING_DECKS_REMINDER_TIME, "%H:%M").time().replace(tzinfo=tz)

    async def _remind_about_missing_decks(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await missing_decks_reminder_job.run(context.bot, now=datetime.now(tz_))

    _remind_about_missing_decks.__name__ = "missing_decks_reminder"
    app.job_queue.run_daily(_remind_about_missing_decks, time=missing_decks_reminder_time)
    logger.info(f"Scheduler: MissingDecksReminderJob registered (daily {MISSING_DECKS_REMINDER_TIME})")

    cellar_catalog_sync_job = CellarCatalogSyncJob()

    async def _sync_cellar_catalog(_context: ContextTypes.DEFAULT_TYPE) -> None:
        await cellar_catalog_sync_job.run()

    _sync_cellar_catalog.__name__ = "cellar_catalog_sync"
    cellar_catalog_sync_time = (
        datetime.strptime(CELLAR_CATALOG_SYNC_TIME, "%H:%M").time().replace(tzinfo=CELLAR_TIMEZONE)
    )
    app.job_queue.run_daily(_sync_cellar_catalog, time=cellar_catalog_sync_time, days=(0,))
    logger.info("Scheduler: CellarCatalogSyncJob registered (Sunday %s Europe/Moscow)", CELLAR_CATALOG_SYNC_TIME)


def _register_schedule_jobs(app: Application) -> None:
    """Вешает джобы создания/напоминания/импорта по строкам расписания (только включённым)."""
    for club in get_clubs():
        club_timezone = club.timezone or settings.TOURNAMENT_TIMEZONE
        tz = ZoneInfo(club_timezone)
        for schedule in club.schedules:
            time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
            create_time = datetime.strptime(time_str, "%H:%M").time().replace(tzinfo=tz)

            create_job = CreateTournamentJob(club, schedule)

            async def _create(context: ContextTypes.DEFAULT_TYPE, _job=create_job, _tz=tz) -> None:
                await _job.run(bot=context.bot, now=datetime.now(_tz))

            _create.__name__ = f"create_tournament[{club.name}/{schedule.weekday}]"
            create_day = (_ptb_day(schedule.weekday) - schedule.create_days_before) % 7
            app.job_queue.run_daily(_create, time=create_time, days=(create_day,))
            logger.info(
                f"Scheduler: {club.name} create {schedule.create_days_before} day(s) before "
                f"{schedule.weekday} at {time_str} ({club_timezone}), "
                f"game at {schedule.game_time}"
            )

            if schedule.reminder_time:
                reminder_time = datetime.strptime(schedule.reminder_time, "%H:%M").time().replace(tzinfo=tz)
                reminder_job = PreStartReminderJob(club, schedule)

                async def _reminder(context: ContextTypes.DEFAULT_TYPE, _job=reminder_job, _tz=tz) -> None:
                    await _job.run(bot=context.bot, now=datetime.now(_tz))

                _reminder.__name__ = f"prestart_reminder[{club.name}/{schedule.weekday}]"
                app.job_queue.run_daily(_reminder, time=reminder_time, days=(_ptb_day(schedule.weekday),))
                logger.info(
                    f"Scheduler: pre-start reminder for '{club.name}' ({schedule.weekday}) at {schedule.reminder_time}"
                )

            for attempt_number, fetch_time_str in enumerate(schedule.aetherhub_fetch_times, start=1):
                fetch_time = datetime.strptime(fetch_time_str, "%H:%M").time().replace(tzinfo=tz)
                event_day_offset = _import_day_offset(schedule.aetherhub_fetch_times, fetch_time_str)
                import_job = AetherhubImportJob(
                    club,
                    schedule,
                    event_day_offset=event_day_offset,
                    attempt_number=attempt_number,
                )

                async def _import(context: ContextTypes.DEFAULT_TYPE, _job=import_job, _tz=tz) -> None:
                    await _job.run(now=datetime.now(_tz), bot=context.bot)

                _import.__name__ = f"aetherhub_import[{club.name}/{schedule.weekday}/{fetch_time_str}]"
                import_day = (_ptb_day(schedule.weekday) + event_day_offset) % 7
                app.job_queue.run_daily(_import, time=fetch_time, days=(import_day,))
                logger.info(
                    "Scheduler: AetherHub import for '%s' (%s%s) at %s",
                    club.name,
                    schedule.weekday,
                    "+1d" if event_day_offset else "",
                    fetch_time_str,
                )


_DAY_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среда",
    "thursday": "четверг",
    "friday": "пятница",
    "saturday": "суббота",
    "sunday": "воскресенье",
}


def _format_club_schedule(club: Club) -> str:
    timezone_suffix = f" ({club.timezone})" if club.timezone and club.timezone != settings.TOURNAMENT_TIMEZONE else ""
    lines = [f"\n{club.title_prefix}{club.name}{timezone_suffix}:"]
    for schedule in club.schedules:
        time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
        day_ru = _DAY_RU.get(schedule.weekday.lower(), schedule.weekday)
        create_day = " накануне" if schedule.create_days_before == 1 else ""
        lines.append(f"  {day_ru}: создание{create_day} {time_str}, игра {schedule.game_time}")
        if schedule.aetherhub_fetch_times:
            lines.append(f"    импорт: {', '.join(schedule.aetherhub_fetch_times)}")
    return "\n".join(lines)


def format_schedule_text() -> str:
    """Возвращает текстовое описание расписания для команды /schedule."""
    tz = settings.TOURNAMENT_TIMEZONE
    lines = [f"📅 Расписание ({tz}):"]
    for club in get_clubs():
        lines.append(_format_club_schedule(club))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy helpers — used in old scheduler tests
# ---------------------------------------------------------------------------


def parse_schedule(schedule_str: str) -> tuple[int, datetime.time]:
    """Парсит строку "friday 19:00" в (weekday_int, time)."""
    parts = schedule_str.lower().split()
    if len(parts) != 2:
        raise ValueError(f"Invalid schedule format: '{schedule_str}'. Expected 'weekday HH:MM'")
    day_str, time_str = parts
    if day_str not in DAYS:
        raise ValueError(f"Unknown weekday: '{day_str}'")
    return DAYS[day_str], datetime.strptime(time_str, "%H:%M").time()
