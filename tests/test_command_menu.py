from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import BotCommandScopeChat

import main
from bot.command_menu import commands_for_user, sync_user_command_menu
from core import models


def _command_names(commands) -> list[str]:
    return [command.command for command in commands]


def test_regular_user_does_not_see_create_tournament(user_svc, user_alice):
    assert "create_tournament" not in _command_names(commands_for_user(user_svc, user_alice.tg_id))


def test_tournament_organizer_sees_create_tournament(db, user_svc, user_alice):
    user = db.get(models.User, user_alice.id)
    user.is_tournament_organizer = True
    db.commit()

    names = _command_names(commands_for_user(user_svc, user.tg_id))

    assert names.count("create_tournament") == 1


def test_combined_organizer_roles_receive_both_commands(db, user_svc, user_alice):
    user = db.get(models.User, user_alice.id)
    user.is_poll_organizer = True
    user.is_tournament_organizer = True
    db.commit()

    names = _command_names(commands_for_user(user_svc, user.tg_id))

    assert names.count("poll") == 1
    assert names.count("create_tournament") == 1


@pytest.mark.asyncio
async def test_sync_user_command_menu_uses_private_chat_scope(db, user_svc, user_alice):
    user = db.get(models.User, user_alice.id)
    user.is_tournament_organizer = True
    db.commit()
    bot = AsyncMock()

    await sync_user_command_menu(bot, user_svc, user.tg_id)

    commands = bot.set_my_commands.await_args.args[0]
    scope = bot.set_my_commands.await_args.kwargs["scope"]
    assert "create_tournament" in _command_names(commands)
    assert isinstance(scope, BotCommandScopeChat)
    assert scope.chat_id == user.tg_id


@pytest.mark.asyncio
async def test_startup_syncs_tournament_organizer_menu(db, user_alice):
    user = db.get(models.User, user_alice.id)
    user.is_tournament_organizer = True
    db.commit()
    tg_id = user.tg_id
    app = SimpleNamespace(bot=AsyncMock())

    with patch("main.SessionLocal", return_value=db):
        await main._set_commands(app)

    organizer_call = next(
        call
        for call in app.bot.set_my_commands.await_args_list
        if isinstance(call.kwargs["scope"], BotCommandScopeChat) and call.kwargs["scope"].chat_id == tg_id
    )
    assert "create_tournament" in _command_names(organizer_call.args[0])
