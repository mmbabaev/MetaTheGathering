"""Tests for deck-registration deeplinks (bot/deeplink.py + handler + /start)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.deeplink import (
    cellar_deeplink,
    deck_deeplink,
    deck_payload,
    fill_missing_deeplink,
    fill_missing_payload,
    is_cellar_payload,
    parse_deck_payload,
    parse_fill_missing_payload,
    parse_registration_payload,
    registration_deeplink,
    registration_payload,
)
from bot.handlers.base import HandlerResult
from bot.handlers.player import PlayerHandler
from bot.messages import CHOOSE_ARCHETYPE, NAME_REQUIRED_FOR_REGISTRATION, TOURNAMENT_NOT_FOUND
from bot.telegram.common import cmd_start
from core.schemas import TournamentCreate


class TestPayload:
    def test_round_trip(self):
        assert parse_deck_payload(deck_payload(42)) == 42

    @pytest.mark.parametrize("bad", ["", "deck_", "deck_x", "deck_1x", "foo_1", "1", None])
    def test_non_deck_payloads_are_none(self, bad):
        assert parse_deck_payload(bad or "") is None

    @pytest.mark.parametrize("payload", ["deck_²", "deck_１２３", "deck_٣"])
    def test_unicode_digits_do_not_crash(self, payload):
        """str.isdigit() пропускает не-ASCII цифры, а int() на них падает — не должны."""
        assert parse_deck_payload(payload) is None

    def test_deeplink_url(self):
        assert deck_deeplink("MyBot", 7) == "https://t.me/MyBot?start=deck_7"

    def test_registration_round_trip(self):
        assert parse_registration_payload(registration_payload(42)) == 42

    @pytest.mark.parametrize("bad", ["", "register_", "register_x", "register_1x", "deck_1", None])
    def test_non_registration_payloads_are_none(self, bad):
        assert parse_registration_payload(bad or "") is None

    def test_registration_deeplink_url(self):
        assert registration_deeplink("MyBot", 7) == "https://t.me/MyBot?start=register_7"

    def test_fill_missing_round_trip(self):
        assert parse_fill_missing_payload(fill_missing_payload(42)) == 42

    @pytest.mark.parametrize("bad", ["", "fill_", "fill_x", "fill_1x", "register_1", "fill_²", None])
    def test_non_fill_missing_payloads_are_none(self, bad):
        assert parse_fill_missing_payload(bad or "") is None

    def test_fill_missing_deeplink_url(self):
        assert fill_missing_deeplink("MyBot", 7) == "https://t.me/MyBot?start=fill_7"

    def test_cellar_deeplink_url_and_payload(self):
        assert cellar_deeplink("MyBot") == "https://t.me/MyBot?start=cellar"
        assert is_cellar_payload("cellar") is True
        assert is_cellar_payload("cellar_extra") is False


@pytest.fixture
def player_handler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    return PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Pauper", chat_id=100))


class TestHandleDeeplinkDeck:
    def test_unknown_tournament(self, player_handler, user_svc):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        assert player_handler.handle_deeplink_deck(99999, tg_id=u.tg_id).text == TOURNAMENT_NOT_FOUND

    def test_no_name_asks_for_name(self, player_handler, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, username="a")  # без first_name
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.needs_name
        assert result.text == NAME_REQUIRED_FOR_REGISTRATION

    def test_no_deck_shows_archetype_choice(self, player_handler, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None

    def test_registered_without_deck_still_shows_choice(self, player_handler, svc, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=None)
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.text == CHOOSE_ARCHETYPE

    def test_has_deck_shows_tournament_card(self, player_handler, svc, user_svc, arch_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        arch = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=arch.id)
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        # карточка турнира, не выбор архетипа
        assert result.text != CHOOSE_ARCHETYPE
        assert isinstance(result, HandlerResult)

    def test_registration_closed_does_not_offer_archetype(self, player_handler, svc, user_svc, tournament):
        """Регистрация закрыта — диплинк ведёт на карточку, а не в выбор архетипа."""
        svc.close_tournament(tournament.id)
        user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")

        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=user.tg_id)

        assert result.text != CHOOSE_ARCHETYPE


class TestHandleDeeplinkRegistration:
    def test_unknown_tournament(self, player_handler, user_svc):
        user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        assert player_handler.handle_deeplink_registration(99999, tg_id=user.tg_id).text == TOURNAMENT_NOT_FOUND

    def test_new_player_starts_registration(self, player_handler, user_svc, tournament):
        user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")

        result = player_handler.handle_deeplink_registration(tournament.id, tg_id=user.tg_id)

        assert result.text == CHOOSE_ARCHETYPE

    def test_registered_without_deck_goes_to_tournament_status(self, player_handler, svc, user_svc, tournament):
        user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
        svc.register_participant(tournament_id=tournament.id, user_id=user.id, archetype_id=None)

        result = player_handler.handle_deeplink_registration(tournament.id, tg_id=user.tg_id)

        assert result.text != CHOOSE_ARCHETYPE
        assert "Pauper" in result.text

    def test_closed_registration_goes_to_tournament_status(self, player_handler, svc, user_svc, tournament):
        svc.close_tournament(tournament.id)
        user = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")

        result = player_handler.handle_deeplink_registration(tournament.id, tg_id=user.tg_id)

        assert result.text != CHOOSE_ARCHETYPE
        assert "Pauper" in result.text
        assert isinstance(result, HandlerResult)


@pytest.mark.asyncio
async def test_cmd_start_routes_fill_missing_deeplink():
    update = MagicMock()
    update.effective_user = MagicMock(id=123)
    update.effective_message = AsyncMock()
    context = MagicMock(args=["fill_42"], user_data={})

    with patch("bot.telegram.common._start_fill_missing_deeplink", new_callable=AsyncMock) as start_fill:
        await cmd_start(update, context)

    start_fill.assert_awaited_once_with(update, context, update.effective_user, 42)


@pytest.mark.asyncio
async def test_cmd_start_routes_cellar_deeplink():
    update = MagicMock()
    update.effective_user = MagicMock(id=123)
    update.effective_message = AsyncMock()
    context = MagicMock(args=["cellar"], user_data={})

    with patch("bot.telegram.common._start_cellar_deeplink", new_callable=AsyncMock) as start_cellar:
        await cmd_start(update, context)

    start_cellar.assert_awaited_once_with(update, context)
