"""Планировщик автоматического создания турниров и импорта AetherHub по расписанию клубов.

⚠️ При добавлении/изменении джоб, времён или расписания клубов ОБЯЗАТЕЛЬНО обнови
`docs/scheduler.md` — это полный перечень автоматических действий по времени и событиям.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from telegram.ext import Application, ContextTypes

from bot.messages import format_decks_revealed, format_meta_gather_completed
from bot.telegram.round_notify import send_round_notifications
from core import models
from core.config import Club, ClubSchedule, app_cfg, settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService
from services.stats import StatsService
from services.tournament import TournamentService

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Club definitions
# ---------------------------------------------------------------------------


def get_clubs() -> list[Club]:
    """Returns the list of configured clubs."""
    clubs = [
        Club(
            name="Goldfish",
            chat_id=app_cfg.goldfish_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/GoldFish",
            title_prefix="🐠 ",
            schedules=[
                ClubSchedule(
                    weekday="thursday",
                    game_time="19:45",
                    create_time="03:10",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
                ClubSchedule(
                    weekday="friday",
                    game_time="19:45",
                    create_time="12:00",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
            ],
        ),
        Club(
            name="Edinorog",
            chat_id=app_cfg.edinorog_chat_id or 0,
            aetherhub_url="https://aetherhub.com/User/Edinorog/",
            title_prefix="🦄 ",
            schedules=[
                ClubSchedule(
                    weekday="monday",
                    game_time="19:30",
                    create_time="12:00",
                    aetherhub_fetch_times=[
                        "20:00",
                        "20:30",
                        "21:00",
                        "21:30",
                        "22:00",
                        "22:30",
                        "23:00",
                        "23:30",
                        "00:00",
                        "00:30",
                    ],
                ),
            ],
        ),
    ]
    if settings.DEBUG:
        clubs.append(
            Club(
                name="Debug",
                chat_id=app_cfg.goldfish_chat_id or 0,
                aetherhub_url="https://aetherhub.com/User/GoldFish",
                title_prefix="[DEBUG] 🐠 ",
                schedules=[
                    ClubSchedule(
                        weekday="thursday",
                        game_time="12:30",
                        create_time="12:30",
                        aetherhub_fetch_times=["12:31"],
                        find_latest=True,
                    )
                ],
            )
        )
    return clubs


# ---------------------------------------------------------------------------
# Job: create tournament
# ---------------------------------------------------------------------------


class CreateTournamentJob:
    """Creates the club's tournament on the scheduled weekday."""

    def __init__(self, club: Club, schedule: ClubSchedule) -> None:
        self.club = club
        self.schedule = schedule

    async def run(self, bot, now: datetime, db=None) -> None:
        logger.info(f"CreateTournamentJob: running for '{self.club.name}', now={now.strftime('%A %H:%M')}")
        if now.weekday() != DAYS[self.schedule.weekday]:
            logger.info(
                f"CreateTournamentJob: skipping '{self.club.name}' — not {self.schedule.weekday} (now={now.strftime('%A')})"
            )
            return

        date_str = now.strftime("%Y-%m-%d")
        title = f"{self.club.title_prefix}{self.club.name} Pauper {now.strftime('%d.%m.%Y')}"
        slug = f"{date_str}-{self.club.name.lower()}-pauper"

        close_db = db is None
        if close_db:
            db = SessionLocal()
        try:
            svc = TournamentService(db)
            try:
                active = svc.get_active_tournament_for_chat(self.club.chat_id or 0)
                if active:
                    svc.close_tournament(active.id)
                    logger.info(f"Closed previous tournament #{active.id} for '{self.club.name}'")

                new_t = svc.create_tournament(
                    TournamentCreate(
                        title=title,
                        chat_id=self.club.chat_id or 0,
                        slug=slug,
                        club=self.club.name,
                    )
                )
                logger.info(f"Created tournament #{new_t.id} '{title}' for '{self.club.name}'")

                if settings.OWNER_CHAT_ID and bot is not None:
                    await bot.send_message(
                        chat_id=settings.OWNER_CHAT_ID,
                        text=(
                            f"🏆 {self.club.name} Pauper — сегодня в {self.schedule.game_time}\n"
                            f"Турнир создан. Регистрация открыта."
                        ),
                    )
            except Exception as e:
                logger.error(f"CreateTournamentJob error for '{self.club.name}': {e}", exc_info=True)
        finally:
            if close_db:
                db.close()


# ---------------------------------------------------------------------------
# Job: AetherHub auto-import
# ---------------------------------------------------------------------------


class AetherhubImportJob:
    """Fetches today's pauper tournament from AetherHub and imports it automatically."""

    def __init__(self, club: Club, schedule: ClubSchedule, aetherhub_service: AetherhubService | None = None) -> None:
        self.club = club
        self.schedule = schedule
        self._aetherhub = aetherhub_service or AetherhubService()

    async def run(self, now: datetime, db=None, bot=None) -> None:
        logger.info(f"AetherhubImportJob: running for '{self.club.name}', now={now.strftime('%A %H:%M')}")
        if not self.club.aetherhub_url:
            logger.warning(f"AetherhubImportJob: no aetherhub_url for '{self.club.name}', skipping")
            return
        if now.weekday() != DAYS[self.schedule.weekday]:
            logger.info(
                f"AetherhubImportJob: skipping '{self.club.name}' — not {self.schedule.weekday} (now={now.strftime('%A')})"
            )
            return

        close_db = db is None
        if close_db:
            db = SessionLocal()

        url: str | None = None
        tournament_id: int | None = None

        try:
            tournament = _find_active_club_tournament(db, self.club.name)
            if not tournament:
                logger.warning(f"AetherhubImportJob: no active tournament for '{self.club.name}'")
                return

            tournament_id = tournament.id
            url = tournament.aetherhub_url

            if not url:
                logger.info(f"AetherhubImportJob: fetching club page for '{self.club.name}'")
                today = None if self.schedule.find_latest else now.date()
                try:
                    url = self._aetherhub.find_todays_pauper_tournament(self.club.aetherhub_url, today=today)
                except Exception:
                    logger.exception(f"AetherhubImportJob: failed to fetch club page for '{self.club.name}'")
                    return
                if not url:
                    logger.info(f"AetherhubImportJob: no pauper tournament found for '{self.club.name}'")
                    return

            logger.info(f"AetherhubImportJob: importing {url} for tournament #{tournament_id}")
            try:
                data = self._aetherhub.fetch_tournament(url)
            except Exception:
                logger.exception(f"AetherhubImportJob: failed to fetch tournament data from {url}")
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
                    await send_round_notifications(
                        bot, db, tournament_id, result.new_round_numbers, datalens_service=DataLensService()
                    )
                except Exception:
                    logger.exception(f"AetherhubImportJob: round notifications failed for #{tournament_id}")

            try:
                await maybe_announce_meta_gather_completed(bot, db, tournament_id)
            except Exception:
                logger.exception(f"AetherhubImportJob: completion announce failed for #{tournament_id}")
        finally:
            if close_db:
                db.close()

        if tournament_id and url:
            db2 = SessionLocal()
            try:
                TournamentService(db2).set_aetherhub_url(tournament_id, url)
            except Exception:
                logger.exception(f"AetherhubImportJob: failed to save aetherhub_url for #{tournament_id}")
            finally:
                db2.close()


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
                    await send_round_notifications(
                        bot, db, tournament_id, result.new_round_numbers, datalens_service=DataLensService()
                    )
                except Exception:
                    logger.exception(f"AetherhubTimedImportJob: round notifications failed for #{tournament_id}")

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


FINAL_REIMPORT_TIME = "06:00"  # утро следующего дня — добрать финальный счёт
FINAL_REIMPORT_WINDOW_DAYS = 2  # окно «недавних» турниров для повторного импорта


class AetherhubFinalReimportJob:
    """Раз в сутки утром перезатягивает недавние турниры, чтобы добрать финальный счёт.

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


class AutoRevealDecksJob:
    """Раз в сутки в REVEAL_DECKS_TIME раскрывает колоды активных турниров этого дня.

    Во время регистрации колоды скрыты (``decks_hidden=True``), чтобы их не копировали.
    Раньше админ раскрывал их кнопкой «Показать колоды»; теперь это происходит
    автоматически вечером. Берём незакрытые турниры со скрытыми колодами, созданные
    сегодня (по таймзоне турниров), и снимаем флаг.
    """

    async def run(self, now: datetime, db=None, bot=None) -> None:
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
                models.Tournament.created_at >= day_start,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def maybe_announce_meta_gather_completed(bot, db, tournament_id: int) -> None:
    """Один раз анонсирует «сбор метагейма завершён», когда турнир сыгран до конца.

    Срабатывает после импорта, когда у всех матчей появился счёт (признак завершения
    турнира + получены финальные стендинги). Идемпотентность — флаг
    ``Tournament.completed_announced_at``: флаг ставим ТОЛЬКО после успешной отправки,
    поэтому сбой отправки не «съедает» анонс — он повторится при следующем импорте.

    Пока шлём владельцу (``settings.OWNER_CHAT_ID``), а не в чат турнира — и в debug,
    и в prod. Позже можно переключить на чат клуба, поменяв адресата здесь.
    """
    if bot is None or not settings.OWNER_CHAT_ID:
        return
    tournament = db.get(models.Tournament, tournament_id)
    if tournament is None or tournament.completed_announced_at is not None:
        return

    svc = AetherhubImportService(db)
    if not svc.is_tournament_complete(tournament_id):
        return

    total = len(TournamentService(db).list_participants_for_tournament(tournament_id))
    meta = StatsService(db).get_tournament_meta(tournament_id)
    with_deck = sum(row.count for row in meta)
    undefeated = svc.get_undefeated_players(tournament_id)
    text = format_meta_gather_completed(tournament.title, total, with_deck, undefeated)

    await bot.send_message(chat_id=settings.OWNER_CHAT_ID, text=text)
    tournament.completed_announced_at = models.utc_now()
    db.commit()
    logger.info("maybe_announce_meta_gather_completed: announced completion for #%s", tournament_id)


def _find_active_club_tournament(db, club_name: str):
    """Find the current non-CLOSED tournament for a club."""
    stmt = (
        select(models.Tournament)
        .where(
            models.Tournament.club == club_name,
            models.Tournament.status != models.TournamentStatus.CLOSED,
        )
        .order_by(models.Tournament.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_scheduler(app: Application) -> None:
    """Registers daily jobs for each club and schedule."""
    tz = ZoneInfo(settings.TOURNAMENT_TIMEZONE)

    for club in get_clubs():
        for schedule in club.schedules:
            time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
            create_time = datetime.strptime(time_str, "%H:%M").time().replace(tzinfo=tz)

            create_job = CreateTournamentJob(club, schedule)

            async def _create(context: ContextTypes.DEFAULT_TYPE, _job=create_job) -> None:
                tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
                await _job.run(bot=context.bot, now=datetime.now(tz_))

            _create.__name__ = f"create_tournament[{club.name}/{schedule.weekday}]"
            app.job_queue.run_daily(_create, time=create_time, days=(_ptb_day(schedule.weekday),))
            logger.info(
                f"Scheduler: {club.name} create on {schedule.weekday} at {time_str} "
                f"({settings.TOURNAMENT_TIMEZONE}), game at {schedule.game_time}"
            )

            for fetch_time_str in schedule.aetherhub_fetch_times:
                fetch_time = datetime.strptime(fetch_time_str, "%H:%M").time().replace(tzinfo=tz)
                import_job = AetherhubImportJob(club, schedule)

                async def _import(context: ContextTypes.DEFAULT_TYPE, _job=import_job) -> None:
                    tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
                    await _job.run(now=datetime.now(tz_), bot=context.bot)

                _import.__name__ = f"aetherhub_import[{club.name}/{schedule.weekday}/{fetch_time_str}]"
                app.job_queue.run_daily(_import, time=fetch_time, days=(_ptb_day(schedule.weekday),))
                logger.info(f"Scheduler: AetherHub import for '{club.name}' ({schedule.weekday}) at {fetch_time_str}")

    timed_job = AetherhubTimedImportJob(AetherhubService())

    async def _timed_import(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await timed_job.run(now=datetime.now(tz_), bot=context.bot)

    app.job_queue.run_repeating(_timed_import, interval=60, first=10)
    logger.info("Scheduler: AetherhubTimedImportJob registered (every 60s)")

    final_job = AetherhubFinalReimportJob(AetherhubService())
    final_time = datetime.strptime(FINAL_REIMPORT_TIME, "%H:%M").time().replace(tzinfo=tz)

    async def _final_reimport(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await final_job.run(now=datetime.now(tz_), bot=context.bot)

    _final_reimport.__name__ = "aetherhub_final_reimport"
    app.job_queue.run_daily(_final_reimport, time=final_time)
    logger.info(f"Scheduler: AetherhubFinalReimportJob registered (daily {FINAL_REIMPORT_TIME})")

    reveal_job = AutoRevealDecksJob()
    reveal_time = datetime.strptime(REVEAL_DECKS_TIME, "%H:%M").time().replace(tzinfo=tz)

    async def _reveal_decks(context: ContextTypes.DEFAULT_TYPE) -> None:
        tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
        await reveal_job.run(now=datetime.now(tz_), bot=context.bot)

    _reveal_decks.__name__ = "auto_reveal_decks"
    app.job_queue.run_daily(_reveal_decks, time=reveal_time)
    logger.info(f"Scheduler: AutoRevealDecksJob registered (daily {REVEAL_DECKS_TIME})")


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
    lines = [f"\n{club.title_prefix}{club.name}:"]
    for schedule in club.schedules:
        time_str = schedule.create_time or settings.TOURNAMENT_CREATE_TIME
        day_ru = _DAY_RU.get(schedule.weekday.lower(), schedule.weekday)
        lines.append(f"  {day_ru}: создание {time_str}, игра {schedule.game_time}")
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
