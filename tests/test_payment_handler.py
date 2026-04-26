"""Tests for PaymentHandler business logic."""

from unittest.mock import MagicMock, patch

import pytest

from bot.handlers.payment import PAYMENT_ERROR, PAYMENT_NOT_CONFIGURED, PaymentHandler
from bot.keyboards import Keyboards
from core.schemas import TournamentCreate
from services.payment_service import PaymentCreated, PaymentService
from services.user import UserService

TOURNAMENT_TITLE = "Pauper 2026-04-26"
TG_ID = 12345


@pytest.fixture
def handler(db):
    user_svc = UserService(db)
    payment_svc = PaymentService(db)
    keyboards = Keyboards()
    return PaymentHandler(payment_svc, user_svc, keyboards)


@pytest.fixture
def user_alice(db):
    from services.user import UserService

    svc = UserService(db)
    return svc.get_or_create(tg_id=TG_ID, username="alice", first_name="Alice", last_name="Smith")


class TestPaymentHandler:
    def test_no_credentials_returns_not_configured(self, handler):
        with patch("bot.handlers.payment.settings") as mock_settings:
            mock_settings.YOOKASSA_SHOP_ID = ""
            mock_settings.YOOKASSA_SECRET_KEY = ""
            result = handler.handle_pay(TG_ID, 1, TOURNAMENT_TITLE)
        assert result.is_alert
        assert result.text == PAYMENT_NOT_CONFIGURED

    def test_api_error_returns_error_message(self, handler, user_alice):
        with patch("bot.handlers.payment.settings") as mock_settings:
            mock_settings.YOOKASSA_SHOP_ID = "test_shop"
            mock_settings.YOOKASSA_SECRET_KEY = "test_key"
            with patch.object(handler.payment_svc, "create_payment", side_effect=Exception("network error")):
                result = handler.handle_pay(TG_ID, 1, TOURNAMENT_TITLE)
        assert result.is_alert
        assert result.text == PAYMENT_ERROR

    def test_success_returns_url_keyboard(self, handler, user_alice):
        fake_result = PaymentCreated(
            url="https://yoomoney.ru/checkout/payments/v2/contract?orderId=abc",
            amount="525.00",
            yookassa_id="22d6d597-000f-5000-9000-145f6df21d6f",
        )
        with patch("bot.handlers.payment.settings") as mock_settings:
            mock_settings.YOOKASSA_SHOP_ID = "test_shop"
            mock_settings.YOOKASSA_SECRET_KEY = "test_key"
            with patch.object(handler.payment_svc, "create_payment", return_value=fake_result):
                result = handler.handle_pay(TG_ID, 1, TOURNAMENT_TITLE)
        assert not result.is_alert
        assert "525.00" in result.text
        assert result.keyboard is not None
        buttons = result.keyboard.inline_keyboard
        assert len(buttons) == 1
        assert buttons[0][0].url == fake_result.url

    def test_success_description_includes_user_name(self, handler, user_alice):
        with patch("bot.handlers.payment.settings") as mock_settings:
            mock_settings.YOOKASSA_SHOP_ID = "test_shop"
            mock_settings.YOOKASSA_SECRET_KEY = "test_key"
            captured = {}
            fake_result = PaymentCreated(url="https://pay.url", amount="525.00", yookassa_id="abc")

            def capture_create(tg_id, tournament_id, description):
                captured["description"] = description
                return fake_result

            with patch.object(handler.payment_svc, "create_payment", side_effect=capture_create):
                handler.handle_pay(TG_ID, 1, TOURNAMENT_TITLE)
        assert "Alice" in captured["description"]
        assert TOURNAMENT_TITLE in captured["description"]
