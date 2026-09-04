from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.telegram.round_results import (
    callback_admin_p2,
    callback_confirm,
    callback_reject,
    callback_send,
    callback_swiss_mode,
    callback_swiss_next_round,
)
from core import models
from core.schemas import TournamentCreate
from services.round_results import RoundResultsService
from services.tournament import TournamentService


def _setup_match(db, user_svc):
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Online", chat_id=1, is_online=True))
    alice = user_svc.get_or_create(tg_id=101, first_name="Алиса", last_name="Иванова")
    bob = user_svc.get_or_create(tg_id=102, first_name="Борис", last_name="Петров")
    db.add_all(
        [
            models.Participant(tournament_id=tournament.id, user_id=alice.id),
            models.Participant(tournament_id=tournament.id, user_id=bob.id),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                table_number=1,
                player_name="Иванова Алиса",
                opponent_name="Петров Борис",
            ),
            models.RoundPairing(
                tournament_id=tournament.id,
                round_number=1,
                table_number=1,
                player_name="Петров Борис",
                opponent_name="Иванова Алиса",
            ),
        ]
    )
    db.commit()
    match = RoundResultsService(db).sync_round(tournament.id, 1)[0]
    return alice, bob, match


def _update(tg_id: int, data: str):
    query = AsyncMock(data=data)
    return SimpleNamespace(effective_user=SimpleNamespace(id=tg_id), callback_query=query), query


async def test_submit_messages_only_the_actual_opponent(db, user_svc):
    alice, bob, match = _setup_match(db, user_svc)
    update, query = _update(alice.tg_id, f"rr_send:{match.id}:2:1")
    bot = AsyncMock()
    refresh = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results._is_notify_allowed", return_value=True),
        patch("bot.telegram.round_results.refresh_club_pairings", refresh),
    ):
        await callback_send(update, SimpleNamespace(bot=bot))

    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == bob.tg_id
    assert "Иванова Алиса 2–1 Петров Борис" in bot.send_message.call_args.kwargs["text"]
    query.edit_message_text.assert_awaited_once()
    refresh.assert_awaited_once_with(bot, db, match.tournament_id, match.round_number)


async def test_notify_allowlist_blocks_result_dm_without_rolling_back_score(db, user_svc):
    alice, _bob, match = _setup_match(db, user_svc)
    update, _query = _update(alice.tg_id, f"rr_send:{match.id}:2:0")
    bot = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results._is_notify_allowed", return_value=False),
    ):
        await callback_send(update, SimpleNamespace(bot=bot))

    bot.send_message.assert_not_awaited()
    assert db.get(models.RoundMatch, match.id).status == models.RoundMatchStatus.PENDING


async def test_confirmation_messages_only_the_original_proposer(db, user_svc):
    alice, bob, match = _setup_match(db, user_svc)
    proposed = RoundResultsService(db).propose(match.id, alice.tg_id, 1, 0)
    update, _query = _update(bob.tg_id, f"rr_yes:{match.id}:{proposed.revision}")
    bot = AsyncMock()
    refresh = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results._is_notify_allowed", return_value=True),
        patch("bot.telegram.round_results.refresh_club_pairings", refresh),
    ):
        await callback_confirm(update, SimpleNamespace(bot=bot))

    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == alice.tg_id
    assert db.get(models.RoundMatch, match.id).status == models.RoundMatchStatus.CONFIRMED
    refresh.assert_awaited_once_with(bot, db, match.tournament_id, match.round_number)


async def test_rejection_refreshes_public_round_message(db, user_svc):
    alice, bob, match = _setup_match(db, user_svc)
    proposed = RoundResultsService(db).propose(match.id, alice.tg_id, 1, 0)
    update, _query = _update(bob.tg_id, f"rr_no:{match.id}:{proposed.revision}")
    bot = AsyncMock()
    refresh = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results._is_notify_allowed", return_value=True),
        patch("bot.telegram.round_results.refresh_club_pairings", refresh),
    ):
        await callback_reject(update, SimpleNamespace(bot=bot))

    refresh.assert_awaited_once_with(bot, db, match.tournament_id, match.round_number)
    assert db.get(models.RoundMatch, match.id).status == models.RoundMatchStatus.UNREPORTED


async def test_admin_result_refreshes_public_round_message(db, user_svc):
    _alice, _bob, match = _setup_match(db, user_svc)
    admin = user_svc.get_or_create(tg_id=999, first_name="Admin")
    admin.is_admin = True
    db.commit()
    update, _query = _update(admin.tg_id, f"rr_ap2:{match.id}:2:0")
    bot = AsyncMock()
    refresh = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results.refresh_club_pairings", refresh),
    ):
        await callback_admin_p2(update, SimpleNamespace(bot=bot))

    refresh.assert_awaited_once_with(bot, db, match.tournament_id, match.round_number)
    assert db.get(models.RoundMatch, match.id).status == models.RoundMatchStatus.ADMIN


async def test_internal_swiss_toggle_and_first_round_publish_only_to_configured_club_chat(db, user_svc, monkeypatch):
    tournament = TournamentService(db).create_tournament(
        TournamentCreate(title="Internal", chat_id=-100500, club="Endstep-ru", is_online=True)
    )
    users = []
    for index in range(4):
        player = user_svc.get_or_create(
            tg_id=500 + index,
            username=f"p{index}",
            first_name=f"Имя{index}",
            last_name=f"Фамилия{index}",
        )
        db.add(models.Participant(tournament_id=tournament.id, user_id=player.id))
        users.append(player)
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr("bot.telegram.round_results.settings.DEBUG", True)

    toggle_update, _ = _update(users[0].tg_id, f"sw_mode:{tournament.id}")
    next_update, next_query = _update(users[0].tg_id, f"sw_next:{tournament.id}")
    publication = AsyncMock(return_value=True)
    bot = AsyncMock()
    with (
        patch("bot.telegram.round_results.SessionLocal", return_value=db),
        patch("bot.telegram.round_results.send_club_pairings", publication),
    ):
        await callback_swiss_mode(toggle_update, SimpleNamespace(bot=bot))
        await callback_swiss_next_round(next_update, SimpleNamespace(bot=bot))

    assert db.get(models.Tournament, tournament.id).engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
    assert db.query(models.RoundPairing).filter_by(tournament_id=tournament.id).count() == 4
    publication.assert_awaited_once_with(bot, db, tournament.id, [1])
    next_query.edit_message_text.assert_awaited_once()
