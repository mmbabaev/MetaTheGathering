"""Tests for the «сбор метагейма завершён» announcement (after a tournament finishes).

Completion is detected from imported pairings: when every non-bye match has a score
(AetherHub publishes scores only AFTER the event) we treat the tournament as finished
and announce, once, to the owner DM — listing the undefeated (X-0) players and their decks.
"""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot import scheduler
from bot.messages import format_meta_gather_completed
from bot.scheduler import maybe_announce_meta_gather_completed
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService, UndefeatedPlayer
from services.tournament import TournamentService


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


# ── scheduler announce helper ───────────────────────────────────────────────


async def test_announces_to_owner_once(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    # график уходит документом, текст — подписью к нему
    bot.send_document.assert_awaited_once()
    kwargs = bot.send_document.call_args.kwargs
    assert kwargs["chat_id"] == 777  # owner DM, not the tournament chat (100)
    assert "Сбор метагейма завершён" in kwargs["caption"]
    assert "Carol — Elves" in kwargs["caption"]
    assert kwargs["filename"] == f"meta_chart_{t.id}.png"
    assert kwargs["document"].getvalue().startswith(b"\x89PNG")
    bot.send_message.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is not None

    # idempotent — a second import must not re-announce
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_document.assert_awaited_once()


async def test_chart_is_rendered_off_the_event_loop_without_db(db, user_svc, arch_svc, monkeypatch):
    """Регрессия: раньше в поток уезжала вся render() вместе с сессией БД.

    Сессия SQLAlchemy для этого не предназначена — на SQLite поток открывал новую пустую
    базу. Теперь в потоке крутится только render_sectors(), которому БД не нужна.
    """
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    t = _complete_tournament(db, user_svc, arch_svc)
    main_thread = threading.get_ident()
    seen = {}

    real_prepare = scheduler.MetaChartService.prepare
    real_render = scheduler.render_sectors

    def spy_prepare(self, tournament_id):
        seen["prepare_thread"] = threading.get_ident()
        return real_prepare(self, tournament_id)

    def spy_render(sectors, subtitle=""):
        seen["render_thread"] = threading.get_ident()
        return real_render(sectors, subtitle)

    monkeypatch.setattr(scheduler.MetaChartService, "prepare", spy_prepare)
    monkeypatch.setattr(scheduler, "render_sectors", spy_render)
    await maybe_announce_meta_gather_completed(AsyncMock(), db, t.id)

    # Работа с БД — в основном потоке: сессию SQLAlchemy в поток отдавать нельзя.
    assert seen["prepare_thread"] == main_thread
    # А ~180 мс рисования — в отдельном, иначе event loop встал бы всему боту.
    assert seen["render_thread"] != main_thread


async def test_announce_falls_back_to_text_when_chart_fails(db, user_svc, arch_svc, monkeypatch):
    """Картинка не должна ломать анонс: рендер упал — текст всё равно уходит."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    monkeypatch.setattr("bot.scheduler.render_sectors", MagicMock(side_effect=RuntimeError("шрифт не найден")))
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_awaited_once()
    assert "Сбор метагейма завершён" in bot.send_message.call_args.kwargs["text"]
    bot.send_document.assert_not_awaited()
    assert db.get(models.Tournament, t.id).completed_announced_at is not None


async def test_long_announce_sends_text_separately(db, user_svc, arch_svc, monkeypatch):
    """Подпись в Telegram ограничена 1024 символами — длинный текст уходит сообщением."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 777)
    monkeypatch.setattr("bot.scheduler.format_meta_gather_completed", MagicMock(return_value="x" * 1100))
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()

    await maybe_announce_meta_gather_completed(bot, db, t.id)

    bot.send_message.assert_awaited_once()
    bot.send_document.assert_awaited_once()
    assert "caption" not in bot.send_document.call_args.kwargs


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


async def test_no_announce_without_owner_chat_id(db, user_svc, arch_svc, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", None)
    t = _complete_tournament(db, user_svc, arch_svc)
    bot = AsyncMock()
    await maybe_announce_meta_gather_completed(bot, db, t.id)
    bot.send_message.assert_not_awaited()
