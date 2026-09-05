from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot.telegram.club_pairings import refresh_club_pairings, send_club_pairings
from core import models
from core.schemas import TournamentCreate
from services.club_pairings import ClubPairingsService
from services.schedule import ScheduleService


def _online_tournament(svc):
    return svc.create_tournament(
        TournamentCreate(title="Endstep Pauper", chat_id=-100123, club="Endstep-ru", is_online=True)
    )


def _add_pair(db, tournament_id, player, opponent, table=1, round_number=1):
    db.add(
        models.RoundPairing(
            tournament_id=tournament_id,
            round_number=round_number,
            player_name=player,
            opponent_name=opponent,
            table_number=table,
        )
    )


def test_pairing_publication_is_off_by_default(db, svc):
    tournament = _online_tournament(svc)
    _add_pair(db, tournament.id, "AliceEndstep", "BobEndstep")
    db.commit()

    assert ClubPairingsService(db).build_for_new_rounds(tournament.id, [1]) is None


def test_online_pairings_use_public_status_format_with_tg_and_real_names(db, svc, user_svc):
    tournament = _online_tournament(svc)
    alice = user_svc.get_or_create(tg_id=1, username="alice_tg", first_name="Alice", last_name="One")
    bob = user_svc.get_or_create(tg_id=2, username="bob_tg", first_name="Bob", last_name="Two")
    alice.endstep_username = "AliceEndstep"
    bob.endstep_username = "BobEndstep"
    _add_pair(db, tournament.id, "AliceEndstep", "BobEndstep")
    _add_pair(db, tournament.id, "BobEndstep", "AliceEndstep")
    settings = models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True)
    db.add(settings)
    db.commit()

    message = ClubPairingsService(db).build_for_new_rounds(tournament.id, [1])

    assert message.chat_id == -100123
    assert "🎮 Endstep Pauper · Регистрация" in message.text
    assert "Раунд 1 · результаты 0/1" in message.text
    assert "1. @alice_tg — @bob_tg" in message.text
    assert "One Alice — Two Bob" in message.text
    assert "Счёт: — · Статус: 🎮 играют" in message.text


def test_endstep_username_resolves_online_aetherhub_name(db, svc, user_svc):
    tournament = _online_tournament(svc)
    user = user_svc.get_or_create(tg_id=3, username="player", first_name="Real", last_name="Name")
    user.endstep_username = "PairingNick"
    db.commit()

    assert ClubPairingsService(db)._import.find_user_by_name("pairingnick", tournament.id).id == user.id


async def test_delivery_posts_single_message_to_club_chat(db, svc):
    tournament = _online_tournament(svc)
    _add_pair(db, tournament.id, "AliceEndstep", None)
    db.add(models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True))
    db.commit()
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="MetaGathererBot")
    bot.send_message.return_value = SimpleNamespace(message_id=321)

    assert await send_club_pairings(bot, db, tournament.id, [1]) is True
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == -100123
    assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    button = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "🎯 Открыть турнир"
    assert button.url == f"https://t.me/MetaGathererBot?start=round_{tournament.id}"
    tracked = db.query(models.TournamentRoundPairingsMessage).one()
    assert (tracked.tournament_id, tracked.round_number, tracked.chat_id, tracked.message_id) == (
        tournament.id,
        1,
        -100123,
        321,
    )


async def test_each_new_round_gets_its_own_editable_message(db, svc):
    tournament = _online_tournament(svc)
    _add_pair(db, tournament.id, "Alice", "Bob", round_number=1)
    _add_pair(db, tournament.id, "Alice", "Carol", round_number=2)
    db.add(models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True))
    db.commit()
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="MetaGathererBot")
    bot.send_message.side_effect = [SimpleNamespace(message_id=321), SimpleNamespace(message_id=654)]

    assert await send_club_pairings(bot, db, tournament.id, [2, 1]) is True
    assert bot.send_message.await_count == 2
    tracked = db.query(models.TournamentRoundPairingsMessage).order_by(models.TournamentRoundPairingsMessage.id).all()
    assert [(row.round_number, row.message_id) for row in tracked] == [(1, 321), (2, 654)]


async def test_refresh_edits_tracked_round_card_with_current_score(db, svc):
    tournament = _online_tournament(svc)
    _add_pair(db, tournament.id, "Alice", "Bob")
    db.add(models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True))
    db.add(
        models.TournamentRoundPairingsMessage(
            tournament_id=tournament.id,
            round_number=1,
            chat_id=-100123,
            message_id=321,
        )
    )
    db.commit()
    match = ClubPairingsService(db)._results.list_round(tournament.id, 1)[0]
    match.player1_wins = 2
    match.player2_wins = 1
    match.status = models.RoundMatchStatus.CONFIRMED
    db.commit()
    bot = AsyncMock()
    bot.get_me.return_value = SimpleNamespace(username="MetaGathererBot")

    assert await refresh_club_pairings(bot, db, tournament.id, 1) is True
    kwargs = bot.edit_message_text.await_args.kwargs
    assert (kwargs["chat_id"], kwargs["message_id"], kwargs["parse_mode"]) == (-100123, 321, "HTML")
    assert "Счёт: <b>2–1</b> · Статус: ✅ подтверждён" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].url.endswith(f"?start=round_{tournament.id}")


async def test_refresh_disables_deleted_round_message(db, svc):
    tournament = _online_tournament(svc)
    _add_pair(db, tournament.id, "Alice", "Bob")
    db.add(models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True))
    tracked = models.TournamentRoundPairingsMessage(
        tournament_id=tournament.id,
        round_number=1,
        chat_id=-100123,
        message_id=321,
    )
    db.add(tracked)
    db.commit()
    bot = AsyncMock()
    bot.edit_message_text.side_effect = BadRequest("Message to edit not found")

    assert await refresh_club_pairings(bot, db, tournament.id, 1) is False
    db.refresh(tracked)
    assert tracked.edit_disabled_at is not None


async def test_no_chat_target_never_attempts_delivery(db, svc):
    tournament = svc.create_tournament(
        TournamentCreate(title="Endstep Pauper", chat_id=0, club="Endstep-ru", is_online=True)
    )
    _add_pair(db, tournament.id, "Alice", None)
    db.add(models.ClubSettingsRow(club_name="Endstep-ru", publish_pairings=True))
    db.commit()
    bot = AsyncMock()

    assert await send_club_pairings(bot, db, tournament.id, [1]) is False
    bot.send_message.assert_not_awaited()


def test_unknown_club_never_publishes(db, svc):
    tournament = svc.create_tournament(TournamentCreate(title="Manual", chat_id=-100456, is_online=True))
    _add_pair(db, tournament.id, "Alice", None)
    db.commit()

    assert ClubPairingsService(db).build_for_new_rounds(tournament.id, [1]) is None
