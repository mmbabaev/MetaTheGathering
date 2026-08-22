from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot.meta_police_message import refresh_meta_police_message
from core import models
from services.meta_police_message import MetaPoliceMessageService


def _track(service, tournament_id, participant_ids):
    return service.upsert(
        tournament_id=tournament_id,
        chat_id=100,
        message_id=321,
        participant_ids=participant_ids,
        button_url=f"https://t.me/TestBot?start=fill_{tournament_id}",
    )


def test_upsert_replaces_message_and_snapshot(db, tournament):
    service = MetaPoliceMessageService(db)
    first = _track(service, tournament.id, [3, 2])
    second = service.upsert(
        tournament_id=tournament.id,
        chat_id=200,
        message_id=654,
        participant_ids=[1],
        button_url=None,
    )

    assert first.id == second.id
    assert second.chat_id == 200
    assert second.message_id == 654
    assert second.participant_ids_json == "[1]"
    assert db.query(models.TournamentMissingDecksReminder).count() == 1


def test_tracked_participants_preserve_snapshot_order(db, svc, user_svc, tournament):
    first_user = user_svc.get_or_create(tg_id=2001, first_name="Первый")
    second_user = user_svc.get_or_create(tg_id=2002, first_name="Второй")
    first = svc.register_participant(tournament_id=tournament.id, user_id=first_user.id)
    second = svc.register_participant(tournament_id=tournament.id, user_id=second_user.id)
    service = MetaPoliceMessageService(db)
    row = _track(service, tournament.id, [second.id, first.id])

    participants = service.tracked_participants(row)

    assert [participant.id for participant in participants] == [second.id, first.id]


def test_new_missing_participant_is_added_to_snapshot(db, svc, user_svc, tournament):
    first_user = user_svc.get_or_create(tg_id=2001, first_name="Первый")
    first = svc.register_participant(tournament_id=tournament.id, user_id=first_user.id)
    service = MetaPoliceMessageService(db)
    row = _track(service, tournament.id, [first.id])
    second_user = user_svc.get_or_create(tg_id=2002, first_name="Второй")
    second = svc.register_participant(tournament_id=tournament.id, user_id=second_user.id)

    participants = service.tracked_participants(row)

    assert [participant.id for participant in participants] == [first.id, second.id]
    assert row.participant_ids_json == f"[{first.id}, {second.id}]"


async def test_refresh_strikes_filled_player_and_keeps_button(db, svc, user_svc, tournament, archetype_burn):
    first_user = user_svc.get_or_create(tg_id=2001, first_name="Глеб")
    second_user = user_svc.get_or_create(tg_id=2002, first_name="Борис")
    first = svc.register_participant(tournament_id=tournament.id, user_id=first_user.id)
    second = svc.register_participant(tournament_id=tournament.id, user_id=second_user.id)
    _track(MetaPoliceMessageService(db), tournament.id, [first.id, second.id])
    svc.set_participant_archetype(participant_id=first.id, archetype_id=archetype_burn.id)
    bot = AsyncMock()

    updated = await refresh_meta_police_message(bot, db, tournament.id)

    assert updated is True
    kwargs = bot.edit_message_text.call_args.kwargs
    assert kwargs["chat_id"] == 100
    assert kwargs["message_id"] == 321
    assert "<s>• Глеб</s>" in kwargs["text"]
    assert "• Борис" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].text == "Записать"
    assert kwargs["parse_mode"] == "HTML"


async def test_refresh_strikes_everyone_and_removes_button(db, svc, user_svc, tournament, archetype_burn):
    first_user = user_svc.get_or_create(tg_id=2001, first_name="Глеб")
    second_user = user_svc.get_or_create(tg_id=2002, first_name="Борис")
    first = svc.register_participant(tournament_id=tournament.id, user_id=first_user.id)
    second = svc.register_participant(tournament_id=tournament.id, user_id=second_user.id)
    _track(MetaPoliceMessageService(db), tournament.id, [first.id, second.id])
    svc.set_participant_archetype(participant_id=first.id, archetype_id=archetype_burn.id)
    svc.set_participant_archetype(participant_id=second.id, archetype_id=archetype_burn.id)
    bot = AsyncMock()

    await refresh_meta_police_message(bot, db, tournament.id)

    kwargs = bot.edit_message_text.call_args.kwargs
    assert "<s>• Глеб</s>" in kwargs["text"]
    assert "<s>• Борис</s>" in kwargs["text"]
    assert "Все колоды заполнены" in kwargs["text"]
    assert kwargs["reply_markup"] is None


async def test_missing_tracked_participant_skips_telegram_edit(db, tournament):
    service = MetaPoliceMessageService(db)
    row = _track(service, tournament.id, [])
    row.participant_ids_json = "[999]"
    db.commit()
    # A missing tracked participant safely produces no Telegram call and does not disable.
    bot = AsyncMock()
    assert await refresh_meta_police_message(bot, db, tournament.id) is False
    bot.edit_message_text.assert_not_awaited()


async def test_message_not_found_disables_tracking(db, svc, user_alice, tournament):
    participant = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
    row = _track(MetaPoliceMessageService(db), tournament.id, [participant.id])
    bot = AsyncMock()
    bot.edit_message_text.side_effect = BadRequest("Message to edit not found")

    assert await refresh_meta_police_message(bot, db, tournament.id) is False

    db.refresh(row)
    assert row.edit_disabled_at is not None
