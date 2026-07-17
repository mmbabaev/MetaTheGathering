"""Tests for deck-registration deeplinks (bot/deeplink.py + handler + /start)."""

import pytest

from bot.deeplink import deck_deeplink, deck_payload, parse_deck_payload
from bot.handlers.base import HandlerResult
from bot.handlers.player import PlayerHandler
from bot.messages import CHOOSE_ARCHETYPE, NAME_REQUIRED_FOR_REGISTRATION, TOURNAMENT_NOT_FOUND
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


@pytest.fixture
def player_handler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features):
    return PlayerHandler(svc, user_svc, arch_svc, keyboards, aetherhub_svc, features)


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Pauper", chat_id=100))


class TestHandleDeeplinkDeck:
    def test_unknown_tournament(self, player_handler, user_svc):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса")
        assert player_handler.handle_deeplink_deck(99999, tg_id=u.tg_id).text == TOURNAMENT_NOT_FOUND

    def test_no_name_asks_for_name(self, player_handler, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, username="a")  # без first_name
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.needs_name
        assert result.text == NAME_REQUIRED_FOR_REGISTRATION

    def test_no_deck_shows_archetype_choice(self, player_handler, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса")
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.text == CHOOSE_ARCHETYPE
        assert result.keyboard is not None

    def test_registered_without_deck_still_shows_choice(self, player_handler, svc, user_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса")
        svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=None)
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        assert result.text == CHOOSE_ARCHETYPE

    def test_has_deck_shows_tournament_card(self, player_handler, svc, user_svc, arch_svc, tournament):
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса")
        arch = arch_svc.get_or_create_by_name("Burn")
        svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=arch.id)
        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)
        # карточка турнира, не выбор архетипа
        assert result.text != CHOOSE_ARCHETYPE
        assert isinstance(result, HandlerResult)

    def test_registration_closed_does_not_offer_archetype(self, player_handler, svc, user_svc, tournament):
        """Регистрация закрыта — диплинк ведёт на карточку, а не в выбор архетипа
        (иначе выбор упал бы TournamentInvalidState)."""
        svc.close_tournament(tournament.id)
        u = user_svc.get_or_create(tg_id=1, first_name="Алиса")

        result = player_handler.handle_deeplink_deck(tournament.id, tg_id=u.tg_id)

        assert result.text != CHOOSE_ARCHETYPE
