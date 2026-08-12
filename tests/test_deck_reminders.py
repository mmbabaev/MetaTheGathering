"""Deferred-deck reminder recipient and Telegram delivery tests."""

from unittest.mock import AsyncMock, patch

from bot.telegram.deck_reminder import send_deferred_deck_reminders
from core import models
from core.schemas import TournamentCreate
from services.deck_reminders import DeckReminderService, DeckReminderStage


def _tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Pauper Friday", chat_id=-100))


def _participant(svc, user_svc, tournament_id, tg_id, *, deferred, archetype_id=None):
    user = user_svc.get_or_create(tg_id=tg_id, first_name=f"Player {tg_id}")
    return svc.register_participant(
        tournament_id=tournament_id,
        user_id=user.id,
        archetype_id=archetype_id,
        deck_deferred=deferred,
    )


def test_pending_recipients_are_only_real_explicitly_deferred_players(
    db, svc, user_svc, arch_svc
):
    tournament = _tournament(svc)
    deck = arch_svc.get_or_create_by_name("Burn")
    deferred = _participant(svc, user_svc, tournament.id, 21801, deferred=True)
    _participant(svc, user_svc, tournament.id, 21802, deferred=False)
    _participant(
        svc,
        user_svc,
        tournament.id,
        21803,
        deferred=True,
        archetype_id=deck.id,
    )
    _participant(svc, user_svc, tournament.id, -21804, deferred=True)

    recipients = DeckReminderService(db).pending_recipients(
        tournament.id,
        DeckReminderStage.PRESTART,
    )

    assert [(row.participant_id, row.tg_id) for row in recipients] == [
        (deferred.id, 21801)
    ]


async def test_prestart_delivery_is_idempotent_and_round2_remains_independent(
    db, svc, user_svc
):
    tournament = _tournament(svc)
    participant = _participant(svc, user_svc, tournament.id, 21811, deferred=True)
    bot = AsyncMock()

    first = await send_deferred_deck_reminders(
        bot,
        db,
        tournament.id,
        DeckReminderStage.PRESTART,
    )
    repeated = await send_deferred_deck_reminders(
        bot,
        db,
        tournament.id,
        DeckReminderStage.PRESTART,
    )
    round2 = await send_deferred_deck_reminders(
        bot,
        db,
        tournament.id,
        DeckReminderStage.ROUND2,
    )

    assert (first, repeated, round2) == (1, 0, 1)
    assert bot.send_message.await_count == 2
    assert "скоро начинается" in bot.send_message.await_args_list[0].kwargs["text"]
    assert "второй раунд" in bot.send_message.await_args_list[1].kwargs["text"]
    row = db.get(models.Participant, participant.id)
    assert row.deck_reminder_prestart_sent_at is not None
    assert row.deck_reminder_round2_sent_at is not None


async def test_successful_delivery_marks_only_successful_recipient(db, svc, user_svc):
    tournament = _tournament(svc)
    good = _participant(svc, user_svc, tournament.id, 21821, deferred=True)
    failed = _participant(svc, user_svc, tournament.id, 21822, deferred=True)
    bot = AsyncMock()

    async def send_message(*, chat_id, **kwargs):
        if chat_id == 21822:
            raise RuntimeError("DM blocked")

    bot.send_message.side_effect = send_message
    sent = await send_deferred_deck_reminders(
        bot,
        db,
        tournament.id,
        DeckReminderStage.PRESTART,
    )

    assert sent == 1
    assert db.get(models.Participant, good.id).deck_reminder_prestart_sent_at is not None
    assert db.get(models.Participant, failed.id).deck_reminder_prestart_sent_at is None


async def test_notify_allow_list_filters_without_marking(db, svc, user_svc):
    tournament = _tournament(svc)
    allowed = _participant(svc, user_svc, tournament.id, 21831, deferred=True)
    blocked = _participant(svc, user_svc, tournament.id, 21832, deferred=True)
    bot = AsyncMock()

    with patch(
        "bot.telegram.deck_reminder._is_notify_allowed",
        side_effect=lambda tg_id: tg_id == 21831,
    ):
        sent = await send_deferred_deck_reminders(
            bot,
            db,
            tournament.id,
            DeckReminderStage.PRESTART,
        )

    assert sent == 1
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 21831
    assert db.get(models.Participant, allowed.id).deck_reminder_prestart_sent_at is not None
    assert db.get(models.Participant, blocked.id).deck_reminder_prestart_sent_at is None
