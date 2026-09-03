from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.base import HandlerResult
from bot.telegram.admin import _parse_create_tournament_args, cmd_create_tournament
from config.debug import app_config as debug_config
from config.prod import app_config as prod_config
from core.clubs import club_identities, default_clubs, default_schedules

ENDSTEP_CHAT_ID = -1003631429183


def test_endstep_ru_identity_is_online_and_has_no_default_schedule():
    identity = next(row for row in club_identities() if row.name == "Endstep-ru")

    assert identity.chat_id == ENDSTEP_CHAT_ID
    assert identity.aetherhub_url == "https://aetherhub.com/User/MetaTheGathering"
    assert identity.title_prefix == "⏭️🦶 "
    assert identity.is_online is True
    assert identity.magicoculus_city is None
    assert identity.timezone == "Europe/Moscow"
    assert all(row.club_name != "Endstep-ru" for row in default_schedules())
    club = next(row for row in default_clubs() if row.name == "Endstep-ru")
    assert club.is_online is True
    assert club.schedules == []


def test_endstep_ru_uses_temporary_test_chat_in_both_environments():
    assert prod_config.endstep_ru_chat_id == ENDSTEP_CHAT_ID
    assert debug_config.endstep_ru_chat_id == ENDSTEP_CHAT_ID


def test_manual_create_args_select_endstep_and_keep_optional_title():
    identity, title, error = _parse_create_tournament_args(["--club", "endstep-RU", "Online", "Pauper"])

    assert error is None
    assert identity is not None
    assert identity.name == "Endstep-ru"
    assert title == "Online Pauper"


def test_manual_create_args_reject_unknown_club():
    identity, title, error = _parse_create_tournament_args(["--club=missing"])

    assert identity is None
    assert title is None
    assert "Неизвестный клуб" in error


@pytest.mark.asyncio
async def test_manual_create_command_targets_endstep_chat_and_sets_club():
    update = MagicMock()
    update.effective_user.id = 42
    update.effective_message = AsyncMock()
    context = MagicMock()
    context.args = ["--club", "Endstep-ru"]
    handler = MagicMock()
    handler.handle_create_tournament.return_value = HandlerResult("✅ Турнир создан", tournament_id=123)
    player = MagicMock()
    player.handle_tournament_select.return_value = HandlerResult("Карточка")

    with (
        patch("bot.telegram.admin.SessionLocal") as session_local,
        patch("bot.telegram.admin._admin_handler", return_value=handler),
        patch("bot.telegram.admin._player_handler", return_value=player),
        patch("bot.telegram.admin._log"),
    ):
        await cmd_create_tournament(update, context)

    handler.handle_create_tournament.assert_called_once_with(
        42,
        ENDSTEP_CHAT_ID,
        None,
        club="Endstep-ru",
        is_online=True,
        title_prefix="⏭️🦶 ",
    )
    session_local.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_create_tournament_without_args_opens_wizard():
    update = MagicMock()
    context = MagicMock()
    context.args = []

    with patch("bot.telegram.create_tournament.cmd_create_tournament_wizard", new_callable=AsyncMock) as wizard:
        await cmd_create_tournament(update, context)

    wizard.assert_awaited_once_with(update, context)
