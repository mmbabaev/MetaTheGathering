from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest

from bot.handlers.create_tournament import CreateTournamentWizardHandler
from bot.keyboards import Keyboards
from bot.tournament_creation import execute_creation_plan, execute_due_creation_plans
from core import models
from core.schemas import TournamentCreate
from services.club_settings import ClubAnnouncementSettingsService
from services.tournament_creation import TournamentCreationPlanService
from services.user import UserService

ADMIN_ID = 88001
NOW = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)  # 12:00 Europe/Moscow


def _handler(db):
    user = UserService(db).get_or_create(tg_id=ADMIN_ID, username="admin")
    user.is_admin = True
    db.commit()
    club_settings = ClubAnnouncementSettingsService(db)
    club_settings.set_destination("Endstep-ru", "test")
    return CreateTournamentWizardHandler(TournamentCreationPlanService(db), UserService(db), Keyboards(), club_settings)


def _complete_draft(handler, draft, *, announce_now=True):
    handler.handle_club(ADMIN_ID, draft, 4, now=NOW)  # Endstep-ru
    if announce_now:
        handler.handle_announce_now(ADMIN_ID, draft, now=NOW)
    else:
        handler.handle_announce_date(ADMIN_ID, draft, "20260904", now=NOW)
        handler.handle_announce_time(ADMIN_ID, draft, "1800", now=NOW)
    handler.handle_event_date(ADMIN_ID, draft, "20260905", now=NOW)
    return handler.handle_event_time(ADMIN_ID, draft, "1930", now=NOW)


def test_wizard_starts_with_club_buttons_and_endstep_icon(db):
    handler = _handler(db)
    result = handler.handle_start(ADMIN_ID)
    labels = [button.text for row in result.keyboard.inline_keyboard for button in row]
    assert "1/4" in result.text
    assert any("⏭️🦶 Endstep-ru" in label for label in labels)
    assert any("Pair of dice" in label for label in labels)
    assert any("Hobby Games" in label for label in labels)

    online_step = handler.handle_club(ADMIN_ID, {}, 4, now=NOW)
    assert online_step.text.startswith("🎮 ⏭️🦶 Endstep-ru")


def test_wizard_builds_immediate_plan_in_club_timezone(db):
    handler = _handler(db)
    draft = {}
    confirmation = _complete_draft(handler, draft)
    assert "сразу после подтверждения" in confirmation.text
    assert "Чат для объявления: https://t.me/metathegatheringtestgroup" in confirmation.text

    result = handler.handle_confirm(ADMIN_ID, draft, now=NOW)
    plan = TournamentCreationPlanService(db).get(result.creation_plan_id)
    assert plan.club_name == "Endstep-ru"
    assert plan.announce_at == datetime(2026, 9, 4, 9, 0)
    assert plan.event_at == datetime(2026, 9, 5, 16, 30)
    assert plan.status == "pending"


def test_wizard_builds_future_publication_plan(db):
    handler = _handler(db)
    draft = {}
    _complete_draft(handler, draft, announce_now=False)

    result = handler.handle_confirm(ADMIN_ID, draft, now=NOW)
    plan = TournamentCreationPlanService(db).get(result.creation_plan_id)
    assert plan.announce_at == datetime(2026, 9, 4, 15, 0)
    assert plan.event_at == datetime(2026, 9, 5, 16, 30)


def test_wizard_rejects_event_before_publication(db):
    handler = _handler(db)
    draft = {}
    handler.handle_club(ADMIN_ID, draft, 4, now=NOW)
    handler.handle_announce_date(ADMIN_ID, draft, "20260905", now=NOW)
    handler.handle_announce_time(ADMIN_ID, draft, "2200", now=NOW)
    handler.handle_event_date(ADMIN_ID, draft, "20260905", now=NOW)

    result = handler.handle_event_time(ADMIN_ID, draft, "1930", now=NOW)
    assert "после публикации" in result.text
    assert result.keyboard is not None


def test_non_admin_cannot_start_wizard(db):
    result = CreateTournamentWizardHandler(
        TournamentCreationPlanService(db),
        UserService(db),
        Keyboards(),
        ClubAnnouncementSettingsService(db),
    ).handle_start(999)
    assert result.keyboard is None
    assert "нет прав" in result.text.lower()


async def test_execute_plan_creates_online_tournament_and_announces(db):
    service = TournamentCreationPlanService(db)
    ClubAnnouncementSettingsService(db).set_destination("Endstep-ru", "test")
    plan = service.create_plan(
        club_name="Endstep-ru",
        created_by_tg_id=ADMIN_ID,
        announce_at=datetime(2026, 9, 4, 9, 0),
        event_at=datetime(2026, 9, 5, 16, 30),
    )
    bot = AsyncMock()
    bot.get_me.return_value.username = "test_bot"
    bot.send_message.return_value.message_id = 123

    result = await execute_creation_plan(bot, db, plan.id)

    assert result.announced is True
    tournament = db.get(models.Tournament, result.tournament_id)
    assert tournament.club == "Endstep-ru"
    assert tournament.is_online is True
    assert tournament.registration_close_at == datetime(2026, 9, 5, 16, 30)
    announcement = bot.send_message.await_args.kwargs["text"]
    assert bot.send_message.await_args.kwargs["chat_id"] == -1003631429183
    assert announcement.startswith("🎮 Endstep-ru Pauper")
    assert "05.09.2026 в 19:30" in announcement
    db.refresh(plan)
    assert plan.status == "completed"
    assert plan.announcement_sent_at is not None


async def test_no_announcement_plan_is_not_blocked_by_other_clubs_using_chat_zero(db, svc):
    svc.create_tournament(TournamentCreate(title="Pair 1", chat_id=0, club="Pair of dice"))
    svc.create_tournament(TournamentCreate(title="Pair 2", chat_id=0, club="Pair of dice"))
    ClubAnnouncementSettingsService(db).set_destination("Endstep-ru", "none")
    service = TournamentCreationPlanService(db)
    plan = service.create_plan(
        club_name="Endstep-ru",
        created_by_tg_id=ADMIN_ID,
        announce_at=models.utc_now() - timedelta(minutes=1),
        event_at=models.utc_now() + timedelta(days=1),
    )

    result = await execute_creation_plan(AsyncMock(), db, plan.id)

    assert result.announcement_skipped is True
    tournament = db.get(models.Tournament, result.tournament_id)
    assert tournament.club == "Endstep-ru"
    assert tournament.chat_id == 0


async def test_failed_announcement_retries_without_duplicate_tournament(db):
    service = TournamentCreationPlanService(db)
    ClubAnnouncementSettingsService(db).set_destination("Endstep-ru", "test")
    plan = service.create_plan(
        club_name="Endstep-ru",
        created_by_tg_id=ADMIN_ID,
        announce_at=models.utc_now() - timedelta(minutes=1),
        event_at=models.utc_now() + timedelta(days=1),
    )
    bot = AsyncMock()
    bot.get_me.return_value.username = "test_bot"
    bot.send_message.side_effect = BadRequest("temporary failure")

    first = await execute_due_creation_plans(bot, db)
    assert first[0].announced is False
    assert db.query(models.Tournament).count() == 1
    db.refresh(plan)
    assert plan.status == "pending"
    assert plan.tournament_id is not None

    bot.send_message.side_effect = None
    bot.send_message.return_value = MagicMock(message_id=124)
    second = await execute_due_creation_plans(bot, db)
    assert second[0].announced is True
    assert db.query(models.Tournament).count() == 1
    db.refresh(plan)
    assert plan.status == "completed"


def test_future_plan_is_not_due(db):
    service = TournamentCreationPlanService(db)
    service.create_plan(
        club_name="Endstep-ru",
        created_by_tg_id=ADMIN_ID,
        announce_at=models.utc_now() + timedelta(hours=1),
        event_at=models.utc_now() + timedelta(days=1),
    )
    assert service.list_due() == []
