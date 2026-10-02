"""Тесты алертов планировщика: доставка, гейт notify_allowed_ids, троттлинг."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.job_alerts import (
    ALERT_THROTTLE_SECONDS,
    JobAlert,
    NullJobAlerts,
    OwnerDmJobAlerts,
    get_job_alerts,
    set_job_alerts,
)

OWNER_ID = 424242
ALERT = JobAlert(job="create_tournament[Goldfish/friday]", reason="limit_reached", summary="Не создал турнир")


@pytest.fixture
def bot():
    return AsyncMock()


@pytest.fixture(autouse=True)
def _reset_default():
    set_job_alerts(None)
    yield
    set_job_alerts(None)


class TestOwnerDmJobAlerts:
    def test_sends_to_owner(self, bot):
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID)
        alerts.bind_bot(bot)

        assert asyncio.run(alerts.send(ALERT)) is True

        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == OWNER_ID
        assert "Не создал турнир" in kwargs["text"]
        assert "create_tournament[Goldfish/friday]" in kwargs["text"]
        assert "limit_reached" in kwargs["text"]

    def test_uses_owner_chat_id_when_not_overridden(self, bot):
        alerts = OwnerDmJobAlerts()
        alerts.bind_bot(bot)
        with patch("services.job_alerts.settings") as mock_settings:
            mock_settings.OWNER_CHAT_ID = OWNER_ID
            mock_settings.notify_allowed_ids = None
            assert asyncio.run(alerts.send(ALERT)) is True

        assert bot.send_message.await_args.kwargs["chat_id"] == OWNER_ID

    def test_silent_when_owner_not_in_notify_allowed_ids(self, bot):
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID)
        alerts.bind_bot(bot)
        with patch("services.job_alerts.settings") as mock_settings:
            mock_settings.OWNER_CHAT_ID = OWNER_ID
            mock_settings.notify_allowed_ids = [777]
            assert asyncio.run(alerts.send(ALERT)) is False

        bot.send_message.assert_not_awaited()

    def test_throttles_repeat_of_the_same_reason(self, bot):
        clock_value = 1000.0
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID, clock=lambda: clock_value)
        alerts.bind_bot(bot)

        assert asyncio.run(alerts.send(ALERT)) is True
        assert asyncio.run(alerts.send(ALERT)) is True

        bot.send_message.assert_awaited_once()

    def test_different_reason_is_not_throttled(self, bot):
        clock_value = 1000.0
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID, clock=lambda: clock_value)
        alerts.bind_bot(bot)

        asyncio.run(alerts.send(ALERT))
        asyncio.run(alerts.send(JobAlert(job=ALERT.job, reason="error", summary="Упало")))

        assert bot.send_message.await_count == 2

    def test_repeats_after_throttle_window(self, bot):
        clock_value = 1000.0

        def clock():
            return clock_value

        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID, throttle_seconds=60, clock=clock)
        alerts.bind_bot(bot)

        asyncio.run(alerts.send(ALERT))
        clock_value += 59
        asyncio.run(alerts.send(ALERT))
        assert bot.send_message.await_count == 1

        clock_value += 2
        asyncio.run(alerts.send(ALERT))
        assert bot.send_message.await_count == 2

    def test_without_bot_nothing_is_sent(self):
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID)

        assert asyncio.run(alerts.send(ALERT)) is False

    def test_telegram_failure_does_not_raise(self):
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("telegram is down")
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID)
        alerts.bind_bot(bot)

        assert asyncio.run(alerts.send(ALERT)) is False

    def test_failure_is_not_throttled(self):
        bot = AsyncMock()
        bot.send_message.side_effect = [RuntimeError("down"), None]
        alerts = OwnerDmJobAlerts(chat_id=OWNER_ID)
        alerts.bind_bot(bot)

        assert asyncio.run(alerts.send(ALERT)) is False
        assert asyncio.run(alerts.send(ALERT)) is True


class TestBackendSelection:
    def test_default_is_owner_dm(self, bot):
        alerts = get_job_alerts(bot)

        assert isinstance(alerts, OwnerDmJobAlerts)
        # Бот привязан сразу — джобе не нужно знать про доставку.
        assert alerts._bot is bot

    def test_backend_can_be_switched(self, bot):
        with patch("services.job_alerts.settings") as mock_settings:
            mock_settings.JOB_ALERTS_BACKEND = "null"
            assert isinstance(get_job_alerts(bot), NullJobAlerts)

    def test_unknown_backend_falls_back_to_owner_dm(self, bot):
        with patch("services.job_alerts.settings") as mock_settings:
            mock_settings.JOB_ALERTS_BACKEND = "sentry-whenever"
            assert isinstance(get_job_alerts(bot), OwnerDmJobAlerts)

    def test_default_instance_is_reused_to_keep_throttle_state(self, bot):
        assert get_job_alerts(bot) is get_job_alerts(bot)

    def test_set_job_alerts_overrides(self):
        null = NullJobAlerts()
        set_job_alerts(null)

        assert get_job_alerts() is null


class TestNullJobAlerts:
    def test_collects_instead_of_sending(self):
        alerts = NullJobAlerts()

        assert asyncio.run(alerts.send(ALERT)) is True
        assert alerts.sent == [ALERT]


def test_throttle_window_is_sane():
    assert ALERT_THROTTLE_SECONDS >= 3600
