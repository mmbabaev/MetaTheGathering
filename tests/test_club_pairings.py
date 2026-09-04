from unittest.mock import AsyncMock

from bot.telegram.club_pairings import send_club_pairings
from core import models
from core.schemas import TournamentCreate
from services.club_pairings import ClubPairingsService
from services.schedule import ScheduleService


def _online_tournament(svc):
    return svc.create_tournament(
        TournamentCreate(title="Endstep Pauper", chat_id=-100123, club="Endstep-ru", is_online=True)
    )


def _add_pair(db, tournament_id, player, opponent, table=1):
    db.add(
        models.RoundPairing(
            tournament_id=tournament_id,
            round_number=1,
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

    assert await send_club_pairings(bot, db, tournament.id, [1]) is True
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == -100123
    assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"


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
