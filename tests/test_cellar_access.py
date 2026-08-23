from datetime import date
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from bot.handlers.cellar import CellarHandler
from bot.keyboards import (
    CB_CELLAR_CANCEL,
    CB_CELLAR_CANCEL_CONFIRM,
    CB_CELLAR_DATE,
    CB_CELLAR_DECK,
    CB_CELLAR_RESERVE,
)
from bot.telegram.cellar import _announce
from core.config import settings
from services.cellar import CellarService
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService
from services.web_auth import verify_magic_token
from web.routes.auth import auth_verify


def _handler(db):
    return CellarHandler(db, UserService(db), FeatureFlagService(db))


EVENT_DATE = date(2026, 8, 24)
TODAY = date(2026, 8, 23)


def _web_url(result):
    return next(button.url for row in result.keyboard.inline_keyboard for button in row if button.url)


def test_cellar_command_is_disabled_by_default(db):
    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
        today=TODAY,
    )

    assert "недоступны" in result.text
    assert result.keyboard is None
    assert UserService(db).get_by_tg_id(1001) is None


def test_cellar_command_creates_personal_one_time_web_link(db, monkeypatch):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    monkeypatch.setattr(settings, "WEB_BASE_URL", "https://debug.example.test")

    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
    )

    url = _web_url(result)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "debug.example.test"
    assert parsed.path == "/auth/verify"
    assert query["next"] == ["/cellar"]
    user = verify_magic_token(db, query["token"][0])
    assert user is not None
    assert user.tg_id == 1001
    assert verify_magic_token(db, query["token"][0]) is None


@pytest.mark.asyncio
async def test_telegram_magic_link_redirects_to_cellar(db):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
        today=TODAY,
    )
    token = parse_qs(urlparse(_web_url(result)).query)["token"][0]

    response = await auth_verify(None, token, "/cellar", db)

    assert response.status_code == 303
    assert response.headers["location"] == "/cellar"


def test_cellar_telegram_flow_reserves_and_cancels_deck(db):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    handler = _handler(db)
    opened = handler.handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
        today=TODAY,
    )
    date_callbacks = [
        button.callback_data for row in opened.keyboard.inline_keyboard for button in row if button.callback_data
    ]
    assert len(date_callbacks) == 4
    assert all(value.startswith(f"{CB_CELLAR_DATE}:") for value in date_callbacks)

    deck = CellarService(db).catalog(EVENT_DATE)[0]
    deck.source_position = 13
    deck.decklist_url = "https://example.test/decklist"
    deck.notes = "Заменить две карты в сайдборде"
    deck.decklist_updated_on = TODAY
    db.commit()
    catalog = handler.handle_date(tg_id=1001, event_date=EVENT_DATE, today=TODAY)
    deck_callbacks = [
        button.callback_data
        for row in catalog.keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith(f"{CB_CELLAR_DECK}:")
    ]
    assert len(deck_callbacks) == 8
    assert "Свободно:" in catalog.text
    assert any(
        "№13" in button.text
        for row in catalog.keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith(f"{CB_CELLAR_DECK}:")
    )
    second_page = handler.handle_date(tg_id=1001, event_date=EVENT_DATE, page=1, today=TODAY)
    assert (
        sum(
            bool(button.callback_data and button.callback_data.startswith(f"{CB_CELLAR_DECK}:"))
            for row in second_page.keyboard.inline_keyboard
            for button in row
        )
        == 8
    )
    assert any(button.text.startswith("2/") for row in second_page.keyboard.inline_keyboard for button in row)

    card = handler.handle_deck(
        tg_id=1001,
        event_date=EVENT_DATE,
        deck_id=deck.id,
        today=TODAY,
    )
    callbacks = [button.callback_data for row in card.keyboard.inline_keyboard for button in row]
    assert any(value and value.startswith(f"{CB_CELLAR_RESERVE}:") for value in callbacks)
    assert "Статус: ▫️ свободна" in card.text
    assert "Заменить две карты" in card.text
    assert any(button.url == "https://example.test/decklist" for row in card.keyboard.inline_keyboard for button in row)

    reserved = handler.handle_reserve(
        tg_id=1001,
        event_date=EVENT_DATE,
        deck_id=deck.id,
        today=TODAY,
    )
    assert reserved.reservation is not None
    assert reserved.result.answer_text == "Колода забронирована."
    assert "Ваша бронь: ✅" in reserved.result.text

    own_card = handler.handle_deck(
        tg_id=1001,
        event_date=EVENT_DATE,
        deck_id=deck.id,
        today=TODAY,
    )
    callbacks = [button.callback_data for row in own_card.keyboard.inline_keyboard for button in row]
    cancel_callback = next(value for value in callbacks if value and value.startswith(f"{CB_CELLAR_CANCEL}:"))
    reservation_id = int(cancel_callback.split(":")[1])
    prompt = handler.handle_cancel_prompt(tg_id=1001, reservation_id=reservation_id)
    assert "Отменить бронь?" in prompt.text
    assert prompt.keyboard.inline_keyboard[0][0].callback_data.startswith(f"{CB_CELLAR_CANCEL_CONFIRM}:")

    cancelled = handler.handle_cancel(
        tg_id=1001,
        reservation_id=reservation_id,
        today=TODAY,
    )
    assert cancelled.cancelled is True
    assert cancelled.result.answer_text == "Бронь отменена."
    assert CellarService(db).active_reservations(EVENT_DATE) == []


def test_cellar_card_does_not_offer_reserved_deck_to_another_player(db):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    handler = _handler(db)
    handler.handle_open(tg_id=1001, username="alice", first_name="Alice", last_name=None, today=TODAY)
    handler.handle_open(tg_id=1002, username="bob", first_name="Bob", last_name=None, today=TODAY)
    deck = CellarService(db).catalog(EVENT_DATE)[0]
    handler.handle_reserve(tg_id=1001, event_date=EVENT_DATE, deck_id=deck.id, today=TODAY)

    card = handler.handle_deck(
        tg_id=1002,
        event_date=EVENT_DATE,
        deck_id=deck.id,
        today=TODAY,
    )

    assert "Статус: 🔒 забронировал(а) Alice" in card.text
    assert not any(
        button.callback_data and button.callback_data.startswith(f"{CB_CELLAR_RESERVE}:")
        for row in card.keyboard.inline_keyboard
        for button in row
    )


def test_cellar_callbacks_reject_stale_date(db):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    handler = _handler(db)
    handler.handle_open(tg_id=1001, username="alice", first_name="Alice", last_name=None, today=TODAY)

    result = handler.handle_date(
        tg_id=1001,
        event_date=date(2026, 8, 17),
        today=TODAY,
    )

    assert result.is_alert is True
    assert "больше недоступна" in result.text


def test_production_coordinator_sees_upcoming_booking_names_usernames_and_decks(db, monkeypatch):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    handler = _handler(db)
    handler.handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name="Player",
        today=TODAY,
    )
    deck = CellarService(db).catalog(EVENT_DATE)[0]
    deck.source_position = 13
    db.commit()
    handler.handle_reserve(tg_id=1001, event_date=EVENT_DATE, deck_id=deck.id, today=TODAY)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")

    coordinator = handler.handle_open(
        tg_id=111,
        username="coordinator",
        first_name="Coordinator",
        last_name=None,
        today=TODAY,
    )
    regular = handler.handle_open(
        tg_id=1002,
        username="bob",
        first_name="Bob",
        last_name=None,
        today=TODAY,
    )

    assert f"Alice Player — @alice — {deck.display_name}" in coordinator.text
    assert "Брони на ближайшие турниры" not in regular.text


@pytest.mark.asyncio
async def test_telegram_reservation_notification_targets_only_owner_in_production(db, user_svc, monkeypatch):
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    user = user_svc.get_or_create(tg_id=1001, username="alice", first_name="Alice")
    reservation = service.reserve(
        deck_id=service.catalog(EVENT_DATE)[0].id,
        user_id=user.id,
        event_date=EVENT_DATE,
        today=TODAY,
    ).reservation
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 333)
    monkeypatch.setattr("core.config._app_cfg.notify_allowed_ids", None)
    bot = AsyncMock()

    assert await _announce(bot, reservation) is True
    assert await _announce(bot, reservation, cancelled=True) is True

    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [333, 333]
    assert all("@alice" in call.kwargs["text"] for call in bot.send_message.await_args_list)
    assert "забронировал(а)" in bot.send_message.await_args_list[0].kwargs["text"]
    assert "отменил(а) бронь" in bot.send_message.await_args_list[1].kwargs["text"]


@pytest.mark.asyncio
async def test_telegram_reservation_notification_targets_only_owner_in_debug(db, user_svc, monkeypatch):
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    user = user_svc.get_or_create(tg_id=1001, username="alice", first_name="Alice")
    reservation = service.reserve(
        deck_id=service.catalog(EVENT_DATE)[0].id,
        user_id=user.id,
        event_date=EVENT_DATE,
        today=TODAY,
    ).reservation
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "CELLAR_COORDINATOR_TG_IDS", "111,222")
    monkeypatch.setattr(settings, "OWNER_CHAT_ID", 333)
    monkeypatch.setattr("core.config._app_cfg.notify_allowed_ids", [333])
    bot = AsyncMock()

    assert await _announce(bot, reservation, cancelled=True) is True

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 333
    assert "@alice" in bot.send_message.await_args.kwargs["text"]
    assert "отменил(а) бронь" in bot.send_message.await_args.kwargs["text"]
