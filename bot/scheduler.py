"""Планировщик автоматического создания турниров и импорта AetherHub по расписанию клубов.

⚠️ При добавлении/изменении джоб, времён или расписания клубов ОБЯЗАТЕЛЬНО обнови
`docs/scheduler.md` — это полный перечень автоматических действий по времени и событиям.
"""

import asyncio
import io
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from telegram import InputMediaPhoto
from telegram.ext import Application, ContextTypes

from bot.chart import build_chart, build_standings
from bot.messages import format_decks_revealed, format_meta_gather_completed
from bot.registration_messages import RegistrationMessageRefreshJob
from bot.registration_messages import send_registration_open as _send_registration_open
from bot.telegram.achievements import send_achievements_report
from bot.telegram.round_notify import send_round_notifications
from core import models
from core.clubs import debug_club, default_clubs
from core.config import Club, ClubSchedule, settings
from core.database import SessionLocal
from core.schemas import TournamentCreate
from services.aetherhub_import_service import MIN_TOURNAMENT_DURATION, AetherhubImportService
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.magicoculus import MagicOculusClient, MagicOculusImporter, MagicOculusTournamentCollector
from services.schedule import ScheduleService
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

                if bot is not None:
                    text = (
                        f"🏆 {self.club.name} Pauper — сегодня в {self.schedule.game_time}\n"
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
            active = TournamentService(db).get_active_tournament_for_chat(self.club.chat_id or 0)
            if active is None:
                logger.info("PreStartReminderJob: no active tournament for '%s'", self.club.name)
                return
            text = (
                f"⏰ {self.club.name} Pauper начинается в {self.schedule.game_time}!\n"
                f"Ещё не записали колоду? Успейте — жмите кнопку ниже."
            )
            await send_registration_open(bot, db, self.club, active.id, text)
        except Exception:
            logger.exception("PreStartReminderJob error for '%s'", self.club.name)
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
        delivered = await _announce_to_targets(bot, db, tournament_id, title, targets, svc, chart_svc)
    except Exception:
        _release_announce(db, tournament_id)  # непредвиденный сбой — пусть повторится позже
        raise
    # 2) Ни один адресат не получил — снимаем бронь, чтобы анонс повторился на следующем импорте.
    if not delivered:
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
    #    Флаг по умолчанию выключен; ошибка внешнего API не откатывает закрытый турнир.
    if FeatureFlagService(db).is_enabled(FeatureFlags.MAGIC_OCULUS_IMPORT):
        try:
            await asyncio.to_thread(import_closed_tournament_to_magicoculus, tournament_id)
        except Exception as exc:
            logger.exception("maybe_announce_meta_gather_completed: Magic Oculus import failed for #%s", tournament_id)
            await _notify_magicoculus_import_error(bot, tournament_id, title, exc)
    logger.info("maybe_announce_meta_gather_completed: announced completion for #%s", tournament_id)


def import_closed_tournament_to_magicoculus(tournament_id: int) -> None:
    """Синхронный worker: собрать, проверить и one-shot импортировать закрытый турнир."""
    db = SessionLocal()
    try:
        tournament = MagicOculusTournamentCollector(db).collect(tournament_id, validate_aetherhub=True)
        client = MagicOculusClient(settings.MAGIC_OCULUS_API_URL)
        MagicOculusImporter(db, client).import_once(tournament, city="Москва")
    finally:
        db.close()


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


async def _announce_to_targets(bot, db, tournament_id: int, title: str, targets: list, svc, chart_svc) -> bool:
    """Собрать отбивку и разослать по адресатам. True — доставлено хотя бы в один чат.

    В каждый чат — одно сообщение-альбом (картинки + текст подписью к первой); не вошедшие в
    альбом картинки — best-effort. Сбой одного адресата не мешает остальным.
    """
    chart = await build_chart(db, tournament_id, chart_svc)
    standings = await build_standings(db, tournament_id)
    total = len(TournamentService(db).list_participants_for_tournament(tournament_id))
    with_deck = sum(s.count for s in chart.sectors) if chart else _decks_count(db, tournament_id)
    undefeated = svc.get_undefeated_players(tournament_id)
    scorekeepers = TournamentService(db).get_deck_recorders(tournament_id, min_count=2)
    text = format_meta_gather_completed(title, total, with_deck, undefeated, scorekeepers)
    images = ([chart] if chart else []) + list(standings)

    delivered = False
    for chat_id in targets:
        try:
            leftover = await _send_announce(bot, chat_id, text, images)
        except Exception:
            logger.exception(
                "maybe_announce_meta_gather_completed: announce to %s failed for #%s", chat_id, tournament_id
            )
            continue
        delivered = True
        await _send_announce_images(bot, chat_id, leftover)
    return delivered


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


async def _send_announce(bot, chat_id: int, text: str, images: list) -> list:
    """Отправить отбивку в один чат одним сообщением: картинки альбомом, текст — подписью к первой.

    Возвращает картинки, не поместившиеся в альбом (для best-effort дослать отдельно).
    Если картинок нет или текст длиннее подписи — шлём текст отдельным сообщением и возвращаем
    все картинки как «остаток». Сбой альбома → фолбэк на текст (анонс важнее картинок).
    """
    if not images or len(text) > _TG_CAPTION_LIMIT:
        await bot.send_message(chat_id=chat_id, text=text)
        return images

    album = images[:_TG_ALBUM_LIMIT]
    media = [InputMediaPhoto(io.BytesIO(img.png), caption=text if i == 0 else None) for i, img in enumerate(album)]
    try:
        await bot.send_media_group(chat_id=chat_id, media=media)
    except Exception:
        logger.exception("maybe_announce_meta_gather_completed: media group failed — шлём текстом")
        await bot.send_message(chat_id=chat_id, text=text)
        return images
    return images[_TG_ALBUM_LIMIT:]


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
        .order_by(models.Tournament.created_at.desc())
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

    registration_refresh_job = RegistrationMessageRefreshJob()

    async def _refresh_registration_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
        await registration_refresh_job.run(context.bot)

    _refresh_registration_messages.__name__ = "registration_message_refresh"
    app.job_queue.run_repeating(_refresh_registration_messages, interval=15, first=15)
    logger.info("Scheduler: RegistrationMessageRefreshJob registered (every 15s)")

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


def _register_schedule_jobs(app: Application) -> None:
    """Вешает джобы создания/напоминания/импорта по строкам расписания (только включённым)."""
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

            if schedule.reminder_time:
                reminder_time = datetime.strptime(schedule.reminder_time, "%H:%M").time().replace(tzinfo=tz)
                reminder_job = PreStartReminderJob(club, schedule)

                async def _reminder(context: ContextTypes.DEFAULT_TYPE, _job=reminder_job) -> None:
                    tz_ = ZoneInfo(settings.TOURNAMENT_TIMEZONE)
                    await _job.run(bot=context.bot, now=datetime.now(tz_))

                _reminder.__name__ = f"prestart_reminder[{club.name}/{schedule.weekday}]"
                app.job_queue.run_daily(_reminder, time=reminder_time, days=(_ptb_day(schedule.weekday),))
                logger.info(
                    f"Scheduler: pre-start reminder for '{club.name}' ({schedule.weekday}) at {schedule.reminder_time}"
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
