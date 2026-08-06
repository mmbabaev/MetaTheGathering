"""Tests for the «сбор метагейма завершён» announcement (after a tournament finishes).

Completion is detected from imported pairings: when every non-bye match has a score
(AetherHub publishes scores only AFTER the event) we treat the tournament as finished
and announce, once, to the owner DM — listing the undefeated (X-0) players and their decks.
"""

import asyncio
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from telegram.error import TelegramError

from bot import chart as chart_mod
from bot import scheduler  # noqa: F401
from bot.messages import format_meta_gather_completed
from bot.scheduler import _aetherhub_no_show_names, maybe_announce_meta_gather_completed
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService, UndefeatedPlayer
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.magicoculus import MagicOculusImportResult
from services.tournament import TournamentService


@pytest.fixture(autouse=True)
def _disable_magicoculus_by_default(db):
    """Tests unrelated to Oculus must not start a real worker/network request."""
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)


def _pairing(db, t_id, rnd, player, opponent, pw, ow):
    db.add(
        models.RoundPairing(
            tournament_id=t_id,
            round_number=rnd,
            player_name=player,
            opponent_name=opponent,
            table_number=1,
            player_wins=pw,
            opponent_wins=ow,
        )
    )


def _register(db, user_svc, t_id, tg_id, first_name, archetype=None, final_place=None):
    user = user_svc.get_or_create(tg_id=tg_id, first_name=first_name)
    TournamentService(db).register_participant(
        tournament_id=t_id, user_id=user.id, archetype_id=archetype.id if archetype else None
    )
    if final_place is not None:
        p = db.query(models.Participant).filter_by(tournament_id=t_id, user_id=user.id).one()
        p.final_place = final_place
    return user


def _complete_tournament(db, user_svc, arch_svc):
    """4-round tournament: Alice & Carol go 4-0, Bob is 3-1, Dave has a draw.

    Pairing rows are crafted per-player (neutral 'Opp' opponents) so each player's
    record is independent — realism of who-beat-whom is irrelevant to the math.
    """
    t = TournamentService(db).create_tournament(TournamentCreate(title="Pauper Friday", chat_id=100))
    # По умолчанию — «настоящий» завершённый турнир: привязан к AetherHub и стартовал 5ч назад,
    # чтобы проходили гарды анонса (aetherhub_url + минимальная длительность).
    row = db.get(models.Tournament, t.id)
    row.aetherhub_url = "https://aetherhub.com/Tourney/RoundTourney/1"
    row.started_at = models.utc_now() - timedelta(hours=5)
    db.commit()
    burn = arch_svc.get_or_create_by_name("Burn")
    elves = arch_svc.get_or_create_by_name("Elves")

    _register(db, user_svc, t.id, 1, "Alice", archetype=burn, final_place=2)
    _register(db, user_svc, t.id, 2, "Carol", archetype=elves, final_place=1)
    _register(db, user_svc, t.id, 3, "Bob", archetype=burn, final_place=3)
    _register(db, user_svc, t.id, 4, "Dave", archetype=elves, final_place=4)

    # Alice 4-0 (last round a bye → opponent None, no score)
    _pairing(db, t.id, 1, "Alice", "Opp", 2, 0)
    _pairing(db, t.id, 2, "Alice", "Opp", 2, 1)
    _pairing(db, t.id, 3, "Alice", "Opp", 2, 0)
    _pairing(db, t.id, 4, "Alice", None, None, None)
    # Carol 4-0
    for r in (1, 2, 3, 4):
        _pairing(db, t.id, r, "Carol", "Opp", 2, 0)
    # Bob 3-1 (one loss)
    _pairing(db, t.id, 1, "Bob", "Opp", 1, 2)
    for r in (2, 3, 4):
        _pairing(db, t.id, r, "Bob", "Opp", 2, 0)
    # Dave: one draw → not pure X-0
    _pairing(db, t.id, 1, "Dave", "Opp", 1, 1)
    for r in (2, 3, 4):
        _pairing(db, t.id, r, "Dave", "Opp", 2, 0)

    db.commit()
    return t


# ── completion detection ────────────────────────────────────────────────────


def test_is_complete_true_when_all_scored(db, user_svc, arch_svc):
    t = _complete_tournament(db, user_svc, arch_svc)
    assert AetherhubImportService(db).is_tournament_complete(t.id) is True


def test_is_complete_false_when_a_match_unscored(db, user_svc, arch_svc):
    t = _complete_tournament(db, user_svc, arch_svc)
    # blank out one non-bye score → tournament not finished yet
    p = db.query(models.RoundPairing).filter_by(tournament_id=t.id, player_name="Bob", round_number=4).one()
    p.player_wins = None
    p.opponent_wins = None
    db.commit()
    assert AetherhubImportService(db).is_tournament_complete(t.id) is False


def test_is_complete_false_without_pairings(db):
    t = TournamentService(db).create_tournament(TournamentCreate(title="Empty", chat_id=1))
    assert AetherhubImportService(db).is_tournament_complete(t.id) is False


# ── undefeated players ──────────────────────────────────────────────────────


def test_undefeated_lists_only_x0_sorted_by_place(db, user_svc, arch_svc):
    t = _complete_tournament(db, user_svc, arch_svc)
    undefeated = AetherhubImportService(db).get_undefeated_players(t.id)
    # Carol (place 1) before Alice (place 2); Bob (loss) and Dave (draw) excluded
    assert [u.player_name for u in undefeated] == ["Carol", "Alice"]
    assert all(u.wins == 4 for u in undefeated)


def test_undefeated_carries_deck_and_name(db, user_svc, arch_svc):
    t = _complete_tournament(db, user_svc, arch_svc)
    by_name = {u.player_name: u for u in AetherhubImportService(db).get_undefeated_players(t.id)}
    assert by_name["Alice"].archetype_name == "Burn"
    assert by_name["Carol"].archetype_name == "Elves"
    assert by_name["Alice"].first_name == "Alice"


def test_undefeated_unmatched_player_has_no_deck(db, user_svc, arch_svc):
    t = _complete_tournament(db, user_svc, arch_svc)
    # a 4-0 player with no bot user / participant
    for r in (1, 2, 3, 4):
        _pairing(db, t.id, r, "Ghost", "Opp", 2, 0)
    db.commit()
    ghost = next(u for u in AetherhubImportService(db).get_undefeated_players(t.id) if u.player_name == "Ghost")
    assert ghost.archetype_name is None
    assert ghost.first_name is None and ghost.last_name is None


# ── message formatting ──────────────────────────────────────────────────────


def test_format_meta_gather_completed():
    undefeated = [
        UndefeatedPlayer("Carol", "Carol", "Smith", "Elves", 1, 4),
        UndefeatedPlayer("Ghost", None, None, None, None, 4),
    ]
    text = format_meta_gather_completed("Pauper Friday", 12, 9, undefeated)
    assert "🎉 Сбор метагейма завершён — Pauper Friday" in text
    assert "Участников: 12 (9 с колодой)" in text
    assert "Без поражений (4-0):" in text
    assert "• Smith Carol — Elves" in text
    assert "• Ghost — колода неизвестна" in text  # fallback name + deck


def test_format_meta_gather_completed_no_undefeated():
    text = format_meta_gather_completed("T", 5, 3, [])
    assert "Без поражений" not in text


def test_format_meta_gather_completed_scorekeepers():
    sk = [
        SimpleNamespace(username="a_wolf02", first_name="Андрей", last_name="Волков", count=13),
        SimpleNamespace(username=None, first_name="Иван", last_name="Петров", count=2),
    ]
    text = format_meta_gather_completed("T", 10, 10, [], scorekeepers=sk)
    assert "🙏 Спасибо за записанные колоды:" in text
    assert "• @a_wolf02 Волков Андрей — 13" in text
    assert "• Петров Иван — 2" in text  # без username — просто имя


def test_format_meta_gather_completed_no_scorekeepers():
    assert "Спасибо" not in format_meta_gather_completed("T", 5, 3, [])


# ── scheduler announce helper ───────────────────────────────────────────────


async def test_announces_to_owner_once(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    # альбом уходит и в чат клуба (100), и владельцу (777); текст — подписью к первой картинке
    assert bot.send_media_group.await_count == 2
    chats = {c.kwargs["chat_id"] for c in bot.send_media_group.call_args_list}
    assert chats == {100, 777}  # club chat + owner DM
    media = bot.send_media_group.call_args_list[0].kwargs["media"]
    assert len(media) >= 2  # график + минимум одна страница стендингов
    assert "Сбор метагейма завершён" in (media[0].caption or "")
    assert "Carol — Elves" in media[0].caption
    assert all(m.caption is None for m in media[1:])  # подпись только у первой
    bot.send_message.assert_not_awaited()  # текст ушёл подписью, а не отдельным сообщением
    assert db.get(models.Tournament, t.id).completed_announced_at is not None
    # после анонса турнир автоматически закрывается
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED

    # idempotent — a second import must not re-announce
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    assert bot.send_media_group.await_count == 2


def test_no_show_names_require_published_standings(db, user_svc, arch_svc):
    t = TournamentService(db).create_tournament(TournamentCreate(title="No standings", chat_id=100))
    deck = arch_svc.get_or_create_by_name("Burn")
    _register(db, user_svc, t.id, 1, "Alice", archetype=deck)
    _register(db, user_svc, t.id, 2, "Bob", archetype=deck)
    db.commit()

    assert _aetherhub_no_show_names(db, t.id) == []


async def test_owner_only_receives_registered_aetherhub_no_shows(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    deck = arch_svc.get_or_create_by_name("Burn")
    _register(db, user_svc, t.id, 5, "No Show", archetype=deck)
    db.commit()
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    calls = {call.kwargs["chat_id"]: call.kwargs["media"][0].caption for call in bot.send_media_group.call_args_list}
    assert "No Show" in calls[777]
    assert "отсутствуют в итоговых стендингах AetherHub (1)" in calls[777]
    assert "No Show" not in calls[100]


async def test_chart_is_rendered_off_the_event_loop_without_db(db, user_svc, arch_svc, monkeypatch):
    """Регрессия: раньше в поток уезжала вся render() вместе с сессией БД.

    Сессия SQLAlchemy для этого не предназначена — на SQLite поток открывал новую пустую
    базу. Теперь в потоке крутится только render_sectors(), которому БД не нужна.
    """
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    main_thread = threading.get_ident()
    seen = {}

    real_prepare = chart_mod.MetaChartService.prepare
    real_render = chart_mod.render_sectors

    def spy_prepare(self, tournament_id):
        seen["prepare_thread"] = threading.get_ident()
        return real_prepare(self, tournament_id)

    def spy_render(sectors, subtitle=""):
        seen["render_thread"] = threading.get_ident()
        return real_render(sectors, subtitle)

    monkeypatch.setattr(chart_mod.MetaChartService, "prepare", spy_prepare)
    monkeypatch.setattr(chart_mod, "render_sectors", spy_render)
    await maybe_announce_meta_gather_completed(AsyncMock(), db, t.id)

    # Работа с БД — в основном потоке: сессию SQLAlchemy в поток отдавать нельзя.
    assert seen["prepare_thread"] == main_thread
    # А ~180 мс рисования — в отдельном, иначе event loop встал бы всему боту.
    assert seen["render_thread"] != main_thread


async def test_announce_text_delivered_when_all_images_fail_to_build(db, user_svc, arch_svc, monkeypatch):
    """Картинки не должны ломать анонс: и график, и стендинги не отрисовались — текст уходит."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    monkeypatch.setattr("bot.chart.render_sectors", MagicMock(side_effect=RuntimeError("шрифт не найден")))
    monkeypatch.setattr("bot.chart.render_standings_pages", MagicMock(side_effect=RuntimeError("bang")))
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert bot.send_message.await_count == 2  # текстом в оба чата (клуб + владелец)
    assert "Сбор метагейма завершён" in bot.send_message.call_args.kwargs["text"]
    bot.send_photo.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is not None


async def test_first_image_carries_caption_rest_none(db, user_svc, arch_svc, monkeypatch):
    """Подпись (текст отбивки) — только у первой картинки альбома, у остальных нет."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    media = bot.send_media_group.call_args.kwargs["media"]
    assert media[0].caption and "Сбор метагейма завершён" in media[0].caption
    assert all(m.caption is None for m in media[1:])


async def test_media_group_failure_falls_back_to_text(db, user_svc, arch_svc, monkeypatch):
    """Отказ альбома (в т.ч. если Telegram его отверг) не теряет анонс: шлём текст и ставим флаг —
    иначе доставленный анонс придёт повторно и зациклится, если альбом отвергается стабильно."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    bot.send_media_group.side_effect = TelegramError("album failed")

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert bot.send_message.await_count == 2  # фолбэк — текст в оба чата
    assert "Сбор метагейма завершён" in bot.send_message.call_args.kwargs["text"]
    assert db.get(models.Tournament, t.id).completed_announced_at is not None


async def test_flag_set_even_if_media_group_errors_unexpectedly(db, user_svc, arch_svc, monkeypatch):
    """Любая ошибка альбома (даже не TelegramError) не должна привести к повторному анонсу."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    bot.send_media_group.side_effect = RuntimeError("нежданная ошибка")

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert bot.send_message.await_count == 2
    assert db.get(models.Tournament, t.id).completed_announced_at is not None


async def test_total_delivery_failure_reannounces(db, user_svc, arch_svc, monkeypatch):
    """Если ни в один чат не доставили (и альбом, и текст упали) — флаг не встаёт, повтор на импорте."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    bot.send_media_group.side_effect = TelegramError("album failed")
    bot.send_message.side_effect = TelegramError("text failed")

    await maybe_announce_meta_gather_completed(bot, db, t.id)  # ошибки адресатов гасятся

    assert db.get(models.Tournament, t.id).completed_announced_at is None
    assert db.get(models.Tournament, t.id).status != models.TournamentStatus.CLOSED

    assert db.get(models.Tournament, t.id).completed_announced_at is None


async def test_db_error_while_building_images_still_sets_flag(db, user_svc, arch_svc, monkeypatch):
    """Сбой БД при построении картинок не должен отравить сессию.

    Иначе анонс уходит, а коммит флага падает — и он приходит заново на каждый импорт.
    """
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    db_error = MagicMock(side_effect=OperationalError("SELECT 1", {}, Exception("connection lost")))
    monkeypatch.setattr(chart_mod.MetaChartService, "prepare", db_error)
    monkeypatch.setattr(chart_mod.StandingsImageService, "prepare", db_error)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert bot.send_message.await_count == 2  # обе картинки отвалились — анонс ушёл текстом в оба чата
    assert db.get(models.Tournament, t.id).completed_announced_at is not None  # и флаг сохранился


async def test_no_announce_when_incomplete(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    p = db.query(models.RoundPairing).filter_by(tournament_id=t.id, player_name="Bob", round_number=4).one()
    p.player_wins = None
    p.opponent_wins = None
    db.commit()

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is None


async def test_no_announce_without_any_target(db, user_svc, arch_svc, monkeypatch):
    """Нет ни владельца, ни чата клуба — слать некуда."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    t = _complete_tournament(db, user_svc, arch_svc)
    db.get(models.Tournament, t.id).chat_id = 0  # чат клуба тоже отсутствует
    db.commit()
    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_message.assert_not_awaited()
    bot.send_media_group.assert_not_awaited()


async def test_announces_to_club_chat_when_no_owner(db, user_svc, arch_svc, monkeypatch):
    """Владельца нет, но чат клуба есть — отбивка уходит в чат клуба."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    t = _complete_tournament(db, user_svc, arch_svc)  # chat_id=100
    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    assert bot.send_media_group.await_count == 1
    assert bot.send_media_group.call_args.kwargs["chat_id"] == 100


async def test_no_announce_without_aetherhub_link(db, user_svc, arch_svc, monkeypatch):
    """Отладочные/ручные турниры без привязки к AetherHub не анонсируются."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    db.get(models.Tournament, t.id).aetherhub_url = None
    db.commit()

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is None


async def test_no_announce_before_min_duration(db, user_svc, arch_svc, monkeypatch):
    """Гард против преждевременного анонса: раньше порога (MIN_TOURNAMENT_DURATION) с начала игры — не завершаем."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    db.get(models.Tournament, t.id).started_at = models.utc_now() - timedelta(hours=1)
    db.commit()

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is None


async def test_no_announce_without_started_at(db, user_svc, arch_svc, monkeypatch):
    """Нет started_at (первый раунд ещё не импортирован) — рано анонсировать."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    db.get(models.Tournament, t.id).started_at = None
    db.commit()

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_not_awaited()


async def test_no_announce_while_a_deck_is_missing(db, user_svc, arch_svc, monkeypatch):
    """Стендинги готовы, но у одного участника нет колоды — метагейм не собран, молчим."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    _register(db, user_svc, t.id, 5, "Eve", archetype=None, final_place=5)  # без колоды

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is None


async def test_announces_once_last_deck_filled(db, user_svc, arch_svc, monkeypatch):
    """Как только заполнена последняя недостающая колода — анонс уходит (триггер записи колоды)."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    eve = _register(db, user_svc, t.id, 5, "Eve", archetype=None, final_place=5)
    bot = AsyncMock()

    # пока у Eve нет колоды — тишина
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()

    # дописали колоду Eve → следующий вызов (после записи колоды) анонсирует
    burn = arch_svc.get_or_create_by_name("Burn")
    db.query(models.Participant).filter_by(tournament_id=t.id, user_id=eve.id).one().archetype_id = burn.id
    db.commit()

    await maybe_announce_meta_gather_completed(bot, db, t.id)
    assert bot.send_media_group.await_count == 2  # клуб + владелец
    assert db.get(models.Tournament, t.id).completed_announced_at is not None


# ── повторный анонс на следующий день (регрессия) ────────────────────────────


async def test_no_repeat_announce_on_next_day_reimport(db, user_svc, arch_svc, monkeypatch):
    """Отбивка ушла вечером — утренний реимпорт следующего дня НЕ должен прислать её снова.

    Живой баг: турнир в понедельник, отбивка пришла во вторник в 09:00, а в среду в 09:00
    те же сообщения пришли повторно.
    """
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)
    first_day_calls = bot.send_media_group.await_count + bot.send_message.await_count
    assert first_day_calls > 0
    bot.reset_mock()

    # следующее утро: финальный реимпорт снова добирает счёт и дёргает тот же анонс
    AetherhubImportService(db).import_tournament(t.id, _same_data_as_imported(db, t.id))
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_flag_survives_session_close_during_send(db, user_svc, arch_svc, monkeypatch):
    """Соседняя задача закрыла общую сессию посреди отправки — флаг всё равно должен уцелеть.

    Корень бага: `SessionLocal` — scoped_session, одна на поток. Пока анонс висел в await,
    другой хендлер вызывал `db.close()`, ORM-объект турнира становился detached, и запись
    флага после отправки уходила «в никуда» — назавтра дубль.
    """
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    async def close_session_midway(*args, **kwargs):
        db.close()  # ровно то, что делает finally соседней задачи
        return None

    bot.send_media_group.side_effect = close_session_midway

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert db.get(models.Tournament, t.id).completed_announced_at is not None
    bot.reset_mock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_media_group.assert_not_awaited()


async def test_concurrent_announces_send_once(db, user_svc, arch_svc, monkeypatch):
    """Две джобы, стартовавшие одновременно, дают ровно одну отбивку на чат."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(0)  # уступаем управление — второй вызов успевает войти
        return None

    bot.send_media_group.side_effect = slow_send

    await asyncio.gather(
        maybe_announce_meta_gather_completed(bot, db, t.id),
        maybe_announce_meta_gather_completed(bot, db, t.id),
    )

    chats = [c.kwargs["chat_id"] for c in bot.send_media_group.await_args_list]
    assert sorted(chats) == [100, 777]  # по одному разу в каждый чат, без дублей


def _same_data_as_imported(db, tournament_id):
    """Данные AetherHub, эквивалентные уже импортированным — как при утреннем реимпорте."""
    rounds = {}
    for p in db.query(models.RoundPairing).filter_by(tournament_id=tournament_id).all():
        rounds.setdefault(p.round_number, []).append(
            AetherhubPairing(
                player=p.player_name,
                opponent=p.opponent_name,
                table_number=p.table_number,
                player_wins=p.player_wins,
                opponent_wins=p.opponent_wins,
            )
        )
    players = sorted({p.player_name for p in db.query(models.RoundPairing).filter_by(tournament_id=tournament_id)})
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/1",
        players=players,
        standings=players,
        rounds=[AetherhubRound(number=n, pairings=ps) for n, ps in sorted(rounds.items())],
    )


# ── ачивки на шве завершения турнира ─────────────────────────────────────────


async def test_achievements_are_processed_after_close(db, user_svc, arch_svc, monkeypatch):
    """Ачивки считаются на том же шве, что и закрытие турнира."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    # Alice записала свою колоду сама → турнир идёт ей в зачёт ачивок
    alice = db.query(models.User).filter_by(tg_id=1).one()
    db.query(models.Participant).filter_by(tournament_id=t.id, user_id=alice.id).one().deck_added_by_tg_id = alice.tg_id
    db.commit()

    await maybe_announce_meta_gather_completed(AsyncMock(), db, t.id)

    codes = {a.code for a in db.query(models.UserAchievement).filter_by(user_id=alice.id).all()}
    assert {"debut", "undefeated"} <= codes


async def test_achievements_failure_does_not_break_announce(db, user_svc, arch_svc, monkeypatch):
    """Падение движка ачивок не должно отменять уже доставленный анонс и закрытие турнира."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)

    async def boom(*args, **kwargs):
        raise RuntimeError("achievements exploded")

    monkeypatch.setattr("bot.scheduler.send_achievements_report", boom)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert db.get(models.Tournament, t.id).completed_announced_at is not None
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED


async def test_magicoculus_import_runs_after_close_when_enabled(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    to_thread = AsyncMock()
    to_thread.return_value = MagicOculusImportResult(tournament_id=145, detail={})
    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", to_thread)
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    t = _complete_tournament(db, user_svc, arch_svc)

    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)

    to_thread.assert_awaited_once_with(scheduler.import_closed_tournament_to_magicoculus, t.id)
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args.kwargs
    assert call["chat_id"] == t.chat_id
    assert "загружен в Magic Oculus" in call["text"]
    button = call["reply_markup"].inline_keyboard[0][0]
    assert button.text == "👁 Открыть в Magic Oculus"
    assert button.url == "https://magicoculus.ru/tournaments/145"


async def test_magicoculus_failure_does_not_break_close(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("API failed")))
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.scheduler.send_achievements_report", AsyncMock())
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED
    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args.kwargs
    assert call["chat_id"] == 777
    assert "Magic Oculus" in call["text"]
    assert "API failed" in call["text"]


async def test_magicoculus_import_can_be_disabled(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    to_thread = AsyncMock()
    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", to_thread)
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    t = _complete_tournament(db, user_svc, arch_svc)

    await maybe_announce_meta_gather_completed(AsyncMock(), db, t.id)

    to_thread.assert_not_awaited()
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED


async def test_magicoculus_import_starts_only_after_tournament_is_closed(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    t = _complete_tournament(db, user_svc, arch_svc)

    async def verify_closed(*args):
        assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED
        return MagicOculusImportResult(tournament_id=145, detail={})

    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", AsyncMock(side_effect=verify_closed))
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))

    await maybe_announce_meta_gather_completed(AsyncMock(), db, t.id)


async def test_magicoculus_success_message_failure_does_not_break_import(
    db, user_svc, arch_svc, monkeypatch
):
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    monkeypatch.setattr(
        "bot.scheduler.asyncio.to_thread",
        AsyncMock(return_value=MagicOculusImportResult(tournament_id=145, detail={})),
    )
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.scheduler.send_achievements_report", AsyncMock())
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramError("club unavailable")

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED


async def test_magicoculus_error_dm_failure_does_not_break_close(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("API failed")))
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.scheduler.send_achievements_report", AsyncMock())
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramError("DM unavailable")

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_awaited_once()
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED


async def test_magicoculus_error_is_not_sent_to_club_when_owner_missing(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    FeatureFlagService(db).toggle(FeatureFlags.MAGIC_OCULUS_IMPORT)
    monkeypatch.setattr("bot.scheduler.asyncio.to_thread", AsyncMock(side_effect=RuntimeError("API failed")))
    monkeypatch.setattr("bot.scheduler._announce_to_targets", AsyncMock(return_value=True))
    monkeypatch.setattr("bot.scheduler.send_achievements_report", AsyncMock())
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).status == models.TournamentStatus.CLOSED
