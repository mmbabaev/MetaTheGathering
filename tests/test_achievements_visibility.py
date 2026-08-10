"""Теневой режим: обычный игрок не должен видеть ачивки вообще нигде.

Это гейт выкатки в прод. Пока флаги `achievementsPublicUi` / `achievementsPlayerDm`
выключены, для игрока фичи не существует: команда молчит, в справке её нет, в меню
команд Telegram её нет, DM не приходят, в чат клуба ничего не добавляется.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from bot.features import FeatureService
from bot.handlers.achievements import AchievementsHandler
from bot.handlers.base import HandlerResult
from bot.messages import HELP_TEXT, HELP_TEXT_ADMIN, format_meta_gather_completed
from bot.telegram.achievements import cmd_achievements, send_achievements_report
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services.achievements import AchievementService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.tournament import TournamentService
from services.user import UserService

OWNER = 424242


@pytest.fixture
def handler(db, ff_svc):
    return AchievementsHandler(AchievementService(db), UserService(db), FeatureService(ff_svc))


@pytest.fixture
def player(user_svc):
    return user_svc.get_or_create(tg_id=6001, first_name="Алиса", last_name="Иванова")


@pytest.fixture
def admin(user_svc):
    user = user_svc.get_or_create(tg_id=6002, first_name="Админ", last_name="Главный")
    user.is_admin = True
    return user


# ── команда ──────────────────────────────────────────────────────────────────


def test_player_request_is_silent(handler, player):
    """Игроку не отвечаем даже отказом: сам отказ выдал бы, что фича есть."""
    result = handler.shelf(tg_id=player.tg_id)

    assert result.silent is True


def test_admin_request_is_not_silent(handler, admin):
    shelf = handler.shelf(tg_id=admin.tg_id)

    assert not hasattr(shelf, "silent")  # это Shelf, а не отказ


@pytest.mark.asyncio
@patch("bot.telegram.achievements.SessionLocal")
@patch("bot.telegram.achievements._handler")
async def test_wrapper_sends_nothing_on_silent(handler_factory, _session_local):
    handler_factory.return_value.shelf.return_value = HandlerResult("недоступна", silent=True)
    update = MagicMock()
    update.effective_user.id = 6001
    update.effective_message.reply_text = AsyncMock()
    update.effective_message.reply_photo = AsyncMock()
    context = MagicMock()
    context.args = None

    await cmd_achievements(update, context)

    update.effective_message.reply_text.assert_not_awaited()
    update.effective_message.reply_photo.assert_not_awaited()


# ── справка и меню команд ────────────────────────────────────────────────────


def test_help_for_players_has_no_achievements():
    assert "achievements" not in HELP_TEXT.lower()


def test_help_for_admins_mentions_achievements():
    assert "achievements" in HELP_TEXT_ADMIN.lower()


def test_command_menu_for_players_has_no_achievements():
    assert "achievements" not in {c.command for c in main._USER_COMMANDS}


def test_command_menu_for_admins_has_achievements():
    assert "achievements" in {c.command for c in main._ADMIN_COMMANDS}


# ── доставка ─────────────────────────────────────────────────────────────────


@pytest.fixture
def played(db, user_svc, archetype_burn):
    user = user_svc.get_or_create(tg_id=6003, first_name="Боб", last_name="Петров")
    created = TournamentService(db).create_tournament(TournamentCreate(title="Pauper 1", chat_id=100))
    t = db.get(models.Tournament, created.id)
    t.club = "Goldfish"
    t.started_at = models.utc_now() - timedelta(days=1)
    TournamentService(db).register_participant(
        tournament_id=t.id, user_id=user.id, archetype_id=archetype_burn.id, deck_added_by_tg_id=user.tg_id
    )
    db.add(
        models.RoundPairing(
            tournament_id=t.id,
            round_number=1,
            player_name="Петров Боб",
            opponent_name="Opp",
            player_wins=2,
            opponent_wins=0,
        )
    )
    t.status = models.TournamentStatus.CLOSED
    db.commit()
    FeatureFlagService(db).ensure_defaults()
    return t, user


@pytest.mark.asyncio
async def test_report_never_reaches_players(db, played, monkeypatch):
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", OWNER)
    tournament, player = played
    bot = AsyncMock()

    await send_achievements_report(bot, db, tournament.id)

    chats = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    chats |= {c.kwargs["chat_id"] for c in bot.send_media_group.await_args_list}
    assert chats == {OWNER}
    assert player.tg_id not in chats
    assert tournament.chat_id not in chats  # и в чат клуба тоже ничего


@pytest.mark.asyncio
async def test_player_dm_flag_alone_changes_nothing(db, played, monkeypatch):
    """Даже если тумблер «слать игрокам» щёлкнули — до фазы 5 адресат прежний."""
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", OWNER)
    tournament, player = played
    FeatureFlagService(db).toggle(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
    bot = AsyncMock()

    await send_achievements_report(bot, db, tournament.id)

    chats = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
    assert chats == {OWNER}
    assert player.tg_id not in chats


def test_club_announcement_says_nothing_about_achievements():
    """В отбивке «сбор метагейма завершён» строки про ачивки быть не должно (это фаза 4)."""
    text = format_meta_gather_completed("Pauper 1", 10, 10, [], [])

    assert "ачив" not in text.lower()
