from datetime import timedelta
from unittest.mock import AsyncMock

from bot.handlers.clubs import ClubSettingsHandler
from bot.keyboards import CB_CLUB_SETTINGS_CHAT, Keyboards
from bot.tournament_creation import execute_creation_plan
from core import models
from services.club_settings import ClubAnnouncementSettingsService
from services.tournament_creation import TournamentCreationPlanService
from services.user import UserService

ADMIN_ID = 77201


def _handler(db):
    user = UserService(db).get_or_create(tg_id=ADMIN_ID, username="club-admin")
    user.is_admin = True
    db.commit()
    settings = ClubAnnouncementSettingsService(db)
    return ClubSettingsHandler(settings, UserService(db), Keyboards()), settings


def _button_texts(result):
    return [button.text for row in result.keyboard.inline_keyboard for button in row]


def test_default_is_none_and_all_clubs_are_listed(db):
    handler, _ = _handler(db)

    result = handler.handle_list(ADMIN_ID)

    labels = _button_texts(result)
    assert len([label for label in labels if "·" in label]) == 5
    assert any("Pair of dice · не отправлять" in label for label in labels)
    assert any("Hobby Games · не отправлять" in label for label in labels)


def test_real_chat_is_only_offered_when_chat_name_is_known(db):
    handler, _ = _handler(db)

    goldfish = _button_texts(handler.handle_club(ADMIN_ID, 0))
    pair_of_dice = _button_texts(handler.handle_club(ADMIN_ID, 2))
    endstep = _button_texts(handler.handle_club(ADMIN_ID, 4))

    assert "📣 Настоящий: @MoscowPauperChat" in goldfish
    assert "📣 Настоящий: Питерский паупер" in pair_of_dice
    assert "📣 Настоящий: @endstep_ru" in endstep


def test_destination_is_persisted_and_marked(db):
    handler, settings = _handler(db)

    result = handler.handle_set_destination(ADMIN_ID, 4, "test")

    assert settings.get_destination("Endstep-ru") == "test"
    assert any(
        button.callback_data == f"{CB_CLUB_SETTINGS_CHAT}:4:test" and button.text.startswith("✅")
        for row in result.keyboard.inline_keyboard
        for button in row
    )


def test_keyboard_hides_real_option_when_chat_is_unknown():
    keyboard = Keyboards().club_settings_chat_keyboard(0, "none", real_chat_label=None)

    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any("Настоящий:" in label for label in labels)


async def test_none_creates_tournament_without_sending_and_completes_plan(db):
    _, settings = _handler(db)
    settings.set_destination("Endstep-ru", "none")
    plan = TournamentCreationPlanService(db).create_plan(
        club_name="Endstep-ru",
        created_by_tg_id=ADMIN_ID,
        announce_at=models.utc_now(),
        event_at=models.utc_now() + timedelta(days=1),
    )
    bot = AsyncMock()

    result = await execute_creation_plan(bot, db, plan.id)

    assert result.announcement_skipped is True
    bot.send_message.assert_not_awaited()
    db.refresh(plan)
    assert plan.status == "completed"
    assert plan.announcement_sent_at is None
    tournament = db.get(models.Tournament, result.tournament_id)
    assert tournament.chat_id == 0


def test_plan_keeps_destination_selected_at_confirmation(db):
    _, settings = _handler(db)
    settings.set_destination("Goldfish", "test")
    plan = TournamentCreationPlanService(db).create_plan(
        club_name="Goldfish",
        created_by_tg_id=ADMIN_ID,
        announce_at=models.utc_now(),
        event_at=models.utc_now() + timedelta(days=1),
    )

    settings.set_destination("Goldfish", "real")
    db.refresh(plan)

    assert plan.announcement_chat_id == -1003631429183
    assert plan.announcement_chat_label == "https://t.me/metathegatheringtestgroup"
