from datetime import datetime, timedelta

import pytest

from bot.handlers.player import PlayerHandler
from bot.telegram.swiss_requirements_reminder import send_swiss_requirements_reminders
from core import models
from core.schemas import TournamentCreate
from services import errors
from services.decklists import MAX_DECKLIST_LENGTH, DecklistService
from services.internal_swiss import InternalSwissService
from services.round_results import RoundResultError
from services.swiss_requirements_reminders import SwissRequirementsReminderService

NOW = datetime(2026, 9, 18, 15, 45)


def _internal_tournament(svc, *, creator=9001, reminders=True):
    return svc.create_tournament(
        TournamentCreate(
            title="Swiss",
            chat_id=-100,
            is_online=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=NOW + timedelta(minutes=15),
            created_by_tg_id=creator,
            decklist_reminders_enabled=reminders,
        )
    )


def _register(svc, user_svc, arch_svc, tournament_id, tg_id, name):
    user = user_svc.get_or_create(tg_id=tg_id, first_name=name, last_name="Игрок")
    archetype = arch_svc.get_or_create_by_name(f"Deck {name}")
    participant = svc.register_participant(
        tournament_id=tournament_id,
        user_id=user.id,
        archetype_id=archetype.id,
        deck_added_by_tg_id=tg_id,
    )
    return user, participant


def test_new_tournaments_are_opted_in_but_flag_can_keep_legacy_event_out(svc):
    fresh = _internal_tournament(svc)
    legacy = _internal_tournament(svc, creator=9002, reminders=False)

    assert fresh.decklist_reminders_enabled is True
    assert legacy.decklist_reminders_enabled is False


def test_internal_swiss_self_registration_requires_archetype(svc, user_svc):
    tournament = _internal_tournament(svc)
    user = user_svc.get_or_create(tg_id=1001, first_name="Алиса")

    with pytest.raises(errors.ParticipantError, match="архетип"):
        svc.register_participant(tournament_id=tournament.id, user_id=user.id)

    # Organizers may still add a placeholder and fill its archetype before round one.
    row = svc.register_participant(tournament_id=tournament.id, user_id=user.id, added_by_admin=True)
    assert row.archetype_id is None


def test_internal_swiss_cannot_be_enabled_without_start_time(svc, user_svc):
    tournament = svc.create_tournament(TournamentCreate(title="No time", chat_id=-101, is_online=True))
    admin = user_svc.get_or_create(tg_id=3001, first_name="Админ")
    admin.is_admin = True
    svc.db.commit()

    with pytest.raises(RoundResultError, match="время начала"):
        InternalSwissService(svc.db).set_enabled(tournament.id, admin.tg_id, True)


def test_first_round_rejects_admin_added_player_without_archetype(svc, user_svc, arch_svc):
    tournament = _internal_tournament(svc)
    admin, _participant = _register(svc, user_svc, arch_svc, tournament.id, 3101, "Админ")
    admin.is_admin = True
    placeholder = user_svc.get_or_create(tg_id=3102, first_name="Игрок")
    svc.register_participant(tournament_id=tournament.id, user_id=placeholder.id, added_by_admin=True)
    svc.db.commit()

    with pytest.raises(RoundResultError, match="архетип"):
        InternalSwissService(svc.db).generate_next_round(tournament.id, admin.tg_id)


def test_decklist_can_be_replaced_only_before_start_and_owner_can_always_read(svc, user_svc, arch_svc, monkeypatch):
    tournament = _internal_tournament(svc)
    _user, participant = _register(svc, user_svc, arch_svc, tournament.id, 1001, "Алиса")
    service = DecklistService(svc.db)

    first = service.save(tournament.id, 1001, "4 Counterspell\n56 cards")
    second = service.save(tournament.id, 1001, "4 Lightning Bolt\n56 cards")
    assert first.raw_text.startswith("4 Counterspell")
    assert second.raw_text.startswith("4 Lightning Bolt")

    with pytest.raises(errors.DecklistError, match="недоступен"):
        service.view(participant.id, 2002)
    assert service.view(participant.id, 9001).raw_text == second.raw_text
    monkeypatch.setattr("services.decklists.settings.OWNER_CHAT_ID", 7777)
    assert service.view(participant.id, 7777).raw_text == second.raw_text

    stored = svc.db.get(models.Tournament, tournament.id)
    stored.status = models.TournamentStatus.ONGOING
    svc.db.commit()
    with pytest.raises(errors.DecklistError, match="нельзя изменить"):
        service.save(tournament.id, 1001, "new")
    assert service.view(participant.id, 1001).raw_text == second.raw_text


def test_closed_swiss_decklists_are_public(svc, user_svc, arch_svc):
    tournament = _internal_tournament(svc)
    _user, participant = _register(svc, user_svc, arch_svc, tournament.id, 1001, "Алиса")
    DecklistService(svc.db).save(tournament.id, 1001, "60 Islands")
    stored = svc.db.get(models.Tournament, tournament.id)
    stored.status = models.TournamentStatus.CLOSED
    svc.db.commit()

    service = DecklistService(svc.db)
    assert service.list_players(tournament.id, 5555)[0].participant_id == participant.id
    assert service.view(participant.id, 5555).raw_text == "60 Islands"


def test_decklist_validation(svc, user_svc, arch_svc):
    tournament = _internal_tournament(svc)
    _register(svc, user_svc, arch_svc, tournament.id, 1001, "Алиса")
    service = DecklistService(svc.db)

    with pytest.raises(errors.DecklistError, match="пустым"):
        service.save(tournament.id, 1001, "   ")
    with pytest.raises(errors.DecklistError, match="слишком длинный"):
        service.save(tournament.id, 1001, "x" * (MAX_DECKLIST_LENGTH + 1))


def test_reminder_selects_only_new_internal_events_with_missing_data(svc, user_svc, arch_svc):
    fresh = _internal_tournament(svc)
    legacy = _internal_tournament(svc, creator=9002, reminders=False)
    _register(svc, user_svc, arch_svc, fresh.id, 1001, "Алиса")
    _register(svc, user_svc, arch_svc, legacy.id, 1002, "Боб")
    draft = svc.create_tournament(
        TournamentCreate(
            title="Draft",
            chat_id=-102,
            is_online=True,
            is_draft=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=NOW + timedelta(minutes=15),
            created_by_tg_id=9003,
            decklist_reminders_enabled=True,
        )
    )
    draft_player = user_svc.get_or_create(tg_id=1003, first_name="Драфтер")
    svc.register_participant(tournament_id=draft.id, user_id=draft_player.id)

    recipients = SwissRequirementsReminderService(svc.db).pending(NOW)

    assert [(row.tg_id, row.missing_archetype, row.missing_decklist) for row in recipients] == [(1001, False, True)]


@pytest.mark.asyncio
async def test_reminder_delivery_is_targeted_idempotent_and_marks_only_success(svc, user_svc, arch_svc, monkeypatch):
    tournament = _internal_tournament(svc)
    _register(svc, user_svc, arch_svc, tournament.id, 1001, "Алиса")
    _register(svc, user_svc, arch_svc, tournament.id, 1002, "Боб")

    class Bot:
        def __init__(self):
            self.calls = []

        async def send_message(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["chat_id"] == 1002:
                raise RuntimeError("blocked")

    monkeypatch.setattr("bot.telegram.swiss_requirements_reminder._is_notify_allowed", lambda _tg_id: True)
    bot = Bot()
    assert await send_swiss_requirements_reminders(bot, svc.db, NOW) == 1
    assert [call["chat_id"] for call in bot.calls] == [1001, 1002]
    assert svc.get_participant(tournament.id, user_svc.get_by_tg_id(1001).id).swiss_requirements_reminder_sent_at
    assert not svc.get_participant(tournament.id, user_svc.get_by_tg_id(1002).id).swiss_requirements_reminder_sent_at

    bot.calls.clear()
    assert await send_swiss_requirements_reminders(bot, svc.db, NOW) == 0
    assert [call["chat_id"] for call in bot.calls] == [1002]


def test_player_card_has_upload_then_read_only_action(db, svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    tournament = _internal_tournament(svc)
    _register(svc, user_svc, arch_svc, tournament.id, 1001, "Алиса")
    handler = PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)

    card = handler.handle_tournament_select(tournament.id, 1001)
    assert any(button.text == "📄 Загрузить деклист" for row in card.keyboard.inline_keyboard for button in row)

    DecklistService(db).save(tournament.id, 1001, "60 cards")
    card = handler.handle_tournament_select(tournament.id, 1001)
    assert any(button.text == "📄 Изменить деклист" for row in card.keyboard.inline_keyboard for button in row)

    db.get(models.Tournament, tournament.id).status = models.TournamentStatus.ONGOING
    db.commit()
    card = handler.handle_tournament_select(tournament.id, 1001)
    assert any(button.text == "📄 Мой деклист" for row in card.keyboard.inline_keyboard for button in row)


def test_draft_player_can_open_decklist_upload_without_archetype(
    svc, user_svc, arch_svc, keyboards, aetherhub_svc, features
):
    tournament = svc.create_tournament(
        TournamentCreate(
            title="Draft",
            chat_id=-103,
            is_online=True,
            is_draft=True,
            engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
            registration_close_at=NOW + timedelta(minutes=15),
            created_by_tg_id=9001,
            decklist_reminders_enabled=False,
        )
    )
    player = user_svc.get_or_create(tg_id=1010, first_name="Draft", last_name="Player")
    handler = PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)
    registration = handler.handle_register(tournament.id, player.tg_id)
    assert registration.tournament_id == tournament.id
    assert svc.get_participant(tournament.id, player.id).archetype_id is None

    result = handler.handle_decklist_start(player.tg_id, tournament.id)

    assert not result.is_alert
    assert "Отправьте деклист" in result.text
    card = handler.handle_tournament_select(tournament.id, player.tg_id)
    assert all(button.text != "🃏 Выбрать колоду" for row in card.keyboard.inline_keyboard for button in row)
