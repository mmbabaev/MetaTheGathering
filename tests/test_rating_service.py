"""Tests for RatingService and RatingHandler."""

import pytest

from bot.handlers.rating import RatingHandler, _deck_noun
from core.schemas import TournamentCreate
from services.rating import RatingService
from services.tournament import TournamentService
from services.user import UserService

CHAT_ID = 200


@pytest.fixture
def rating_svc(db):
    return RatingService(db)


@pytest.fixture
def handler(db):
    return RatingHandler(TournamentService(db), UserService(db))


@pytest.fixture
def tournament(svc):
    return svc.create_tournament(TournamentCreate(title="Rating Test", chat_id=CHAT_ID))


# ── RatingService.count_decks_added_by ───────────────────────────────────────


class TestCountDecksAddedBy:
    def test_returns_zero_when_no_decks(self, rating_svc, user_alice):
        assert rating_svc.count_decks_added_by(user_alice.tg_id) == 0

    def test_counts_own_deck(self, svc, rating_svc, user_alice, archetype_burn, tournament):
        svc.register_participant(
            tournament_id=tournament.id,
            user_id=user_alice.id,
            archetype_id=archetype_burn.id,
            deck_added_by_tg_id=user_alice.tg_id,
        )
        assert rating_svc.count_decks_added_by(user_alice.tg_id) == 1

    def test_counts_multiple_decks_by_same_user(self, svc, user_svc, rating_svc, archetype_burn, tournament):
        admin = user_svc.get_or_create(tg_id=9000, username="admin", first_name="Admin")
        for i in range(3):
            player = user_svc.get_or_create(tg_id=9100 + i, username=None, first_name=f"Player{i}")
            svc.register_participant(
                tournament_id=tournament.id,
                user_id=player.id,
                archetype_id=archetype_burn.id,
                deck_added_by_tg_id=admin.tg_id,
            )
        assert rating_svc.count_decks_added_by(admin.tg_id) == 3

    def test_does_not_count_other_users_decks(self, svc, user_svc, rating_svc, archetype_burn, tournament):
        alice = user_svc.get_or_create(tg_id=9200, username="alice2", first_name="Alice")
        bob = user_svc.get_or_create(tg_id=9201, username="bob2", first_name="Bob")
        svc.register_participant(
            tournament_id=tournament.id,
            user_id=bob.id,
            archetype_id=archetype_burn.id,
            deck_added_by_tg_id=alice.tg_id,
        )
        assert rating_svc.count_decks_added_by(bob.tg_id) == 0

    def test_ignores_participants_without_deck_added_by(self, svc, rating_svc, user_alice, tournament):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        assert rating_svc.count_decks_added_by(user_alice.tg_id) == 0


# ── RatingService.top_deck_contributors ──────────────────────────────────────


class TestTopDeckContributors:
    def test_empty_when_no_decks(self, rating_svc):
        assert rating_svc.top_deck_contributors() == []

    def test_returns_single_contributor(self, svc, user_svc, rating_svc, archetype_burn, tournament):
        admin = user_svc.get_or_create(tg_id=9300, username="admin3", first_name="Admin")
        player = user_svc.get_or_create(tg_id=9301, username=None, first_name="Player")
        svc.register_participant(
            tournament_id=tournament.id,
            user_id=player.id,
            archetype_id=archetype_burn.id,
            deck_added_by_tg_id=admin.tg_id,
        )
        result = rating_svc.top_deck_contributors()
        assert len(result) == 1
        assert result[0][0].tg_id == admin.tg_id
        assert result[0][1] == 1

    def test_sorted_by_count_desc(self, svc, user_svc, rating_svc, arch_svc, tournament):
        burn = arch_svc.get_or_create_by_name("Burn")
        alice = user_svc.get_or_create(tg_id=9400, username="alice4", first_name="Alice")
        bob = user_svc.get_or_create(tg_id=9401, username="bob4", first_name="Bob")

        # Alice records 1 deck, Bob records 3 decks
        p1 = user_svc.get_or_create(tg_id=9410, username=None, first_name="P1")
        svc.register_participant(
            tournament_id=tournament.id, user_id=p1.id, archetype_id=burn.id, deck_added_by_tg_id=alice.tg_id
        )
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=CHAT_ID + 1))
        for i, tg in enumerate([9411, 9412, 9413]):
            p = user_svc.get_or_create(tg_id=tg, username=None, first_name=f"P{i + 2}")
            svc.register_participant(
                tournament_id=t2.id, user_id=p.id, archetype_id=burn.id, deck_added_by_tg_id=bob.tg_id
            )

        result = rating_svc.top_deck_contributors()
        assert result[0][0].tg_id == bob.tg_id
        assert result[0][1] == 3
        assert result[1][0].tg_id == alice.tg_id
        assert result[1][1] == 1

    def test_respects_limit(self, svc, user_svc, rating_svc, arch_svc):
        burn = arch_svc.get_or_create_by_name("Burn")
        for i in range(5):
            admin = user_svc.get_or_create(tg_id=9500 + i, username=None, first_name=f"Admin{i}")
            t = svc.create_tournament(TournamentCreate(title=f"T{i}", chat_id=CHAT_ID + 10 + i))
            player = user_svc.get_or_create(tg_id=9600 + i, username=None, first_name=f"Player{i}")
            svc.register_participant(
                tournament_id=t.id, user_id=player.id, archetype_id=burn.id, deck_added_by_tg_id=admin.tg_id
            )
        assert len(rating_svc.top_deck_contributors(limit=3)) == 3

    def test_excludes_null_deck_added_by(self, svc, rating_svc, user_alice, tournament):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        assert rating_svc.top_deck_contributors() == []

    def test_exclude_tg_ids_hides_specified_users(self, svc, user_svc, rating_svc, arch_svc, tournament):
        burn = arch_svc.get_or_create_by_name("Burn")
        excluded = user_svc.get_or_create(tg_id=9550, username="boss", first_name="Boss")
        regular = user_svc.get_or_create(tg_id=9551, username="regular", first_name="Regular")
        player1 = user_svc.get_or_create(tg_id=9560, username=None, first_name="P1")
        player2 = user_svc.get_or_create(tg_id=9561, username=None, first_name="P2")
        t2 = svc.create_tournament(TournamentCreate(title="T_excl", chat_id=CHAT_ID + 50))
        svc.register_participant(
            tournament_id=tournament.id, user_id=player1.id, archetype_id=burn.id, deck_added_by_tg_id=excluded.tg_id
        )
        svc.register_participant(
            tournament_id=t2.id, user_id=player2.id, archetype_id=burn.id, deck_added_by_tg_id=regular.tg_id
        )
        result = rating_svc.top_deck_contributors(exclude_tg_ids=[excluded.tg_id])
        tg_ids = [u.tg_id for u, _ in result]
        assert excluded.tg_id not in tg_ids
        assert regular.tg_id in tg_ids

    def test_no_exclusion_returns_all(self, svc, user_svc, rating_svc, arch_svc, tournament):
        burn = arch_svc.get_or_create_by_name("Burn")
        user = user_svc.get_or_create(tg_id=9552, username="someone", first_name="Someone")
        player = user_svc.get_or_create(tg_id=9562, username=None, first_name="P")
        svc.register_participant(
            tournament_id=tournament.id, user_id=player.id, archetype_id=burn.id, deck_added_by_tg_id=user.tg_id
        )
        result = rating_svc.top_deck_contributors()
        assert any(u.tg_id == user.tg_id for u, _ in result)


# ── RatingHandler.handle_social_rating ───────────────────────────────────────


class TestHandleSocialRating:
    def test_no_contributors_returns_empty_message(self, handler):
        result = handler.handle_social_rating(tg_id=1)
        assert "никто" in result.text

    def test_shows_top_contributors(self, db, svc, user_svc, arch_svc):
        burn = arch_svc.get_or_create_by_name("Burn")
        admin = user_svc.get_or_create(tg_id=9700, username="hero", first_name="Иван", last_name="Петров")
        player = user_svc.get_or_create(tg_id=9701, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=CHAT_ID + 20))
        svc.register_participant(
            tournament_id=t.id, user_id=player.id, archetype_id=burn.id, deck_added_by_tg_id=admin.tg_id
        )
        h = RatingHandler(svc, user_svc)
        result = h.handle_social_rating(tg_id=1)
        assert "Иван" in result.text or "Петров" in result.text
        assert "1" in result.text
        assert "🥇" in result.text

    def test_shows_username_when_available(self, db, svc, user_svc, arch_svc):
        burn = arch_svc.get_or_create_by_name("Burn")
        admin = user_svc.get_or_create(tg_id=9800, username="hero2", first_name="Hero")
        player = user_svc.get_or_create(tg_id=9801, username=None, first_name="Player")
        t = svc.create_tournament(TournamentCreate(title="T2", chat_id=CHAT_ID + 30))
        svc.register_participant(
            tournament_id=t.id, user_id=player.id, archetype_id=burn.id, deck_added_by_tg_id=admin.tg_id
        )
        h = RatingHandler(svc, user_svc)
        result = h.handle_social_rating(tg_id=1)
        assert "@hero2" in result.text


# ── _deck_noun ────────────────────────────────────────────────────────────────


class TestDeckNoun:
    def test_one(self):
        assert _deck_noun(1) == "колода"

    def test_two(self):
        assert _deck_noun(2) == "колоды"

    def test_five(self):
        assert _deck_noun(5) == "колод"

    def test_eleven(self):
        assert _deck_noun(11) == "колод"

    def test_twenty_one(self):
        assert _deck_noun(21) == "колода"
