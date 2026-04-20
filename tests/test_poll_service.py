"""Tests for PollService and AdminHandler.handle_create_poll."""

import pytest

from services.poll import PollService
from services.user import UserService
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from bot.handlers.admin import AdminHandler
from bot.handlers.base import HandlerResult


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def poll_svc(db):
    return PollService(db)


@pytest.fixture
def admin_handler(db):
    return AdminHandler(TournamentService(db), UserService(db), ArchetypeService(db))


@pytest.fixture
def admin_user(user_svc):
    u = user_svc.get_or_create(tg_id=9001, username="admin")
    u.is_admin = True
    user_svc.db.commit()
    return u


# ── PollService.create_poll ──────────────────────────────────────────────────

class TestCreatePoll:
    def test_creates_poll(self, poll_svc, tournament):
        poll = poll_svc.create_poll(
            tournament_id=tournament.id,
            chat_id=100,
            tg_poll_id="poll_abc",
            message_id=42,
        )
        assert poll.id is not None
        assert poll.tg_poll_id == "poll_abc"
        assert poll.tournament_id == tournament.id

    def test_get_poll_for_tournament(self, poll_svc, tournament):
        assert poll_svc.get_poll_for_tournament(tournament.id) is None
        poll_svc.create_poll(tournament.id, 100, "p1", 1)
        found = poll_svc.get_poll_for_tournament(tournament.id)
        assert found is not None
        assert found.tg_poll_id == "p1"

    def test_get_poll_by_tg_id(self, poll_svc, tournament):
        poll_svc.create_poll(tournament.id, 100, "tgpoll_xyz", 10)
        found = poll_svc.get_poll_by_tg_id("tgpoll_xyz")
        assert found is not None
        assert found.tournament_id == tournament.id

    def test_get_poll_by_tg_id_not_found(self, poll_svc):
        assert poll_svc.get_poll_by_tg_id("nonexistent") is None


# ── PollService.upsert_vote ──────────────────────────────────────────────────

class TestUpsertVote:
    def test_creates_vote(self, poll_svc, tournament):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, tg_user_id=555, choice=0)
        from sqlalchemy import select
        from core.models import PollVote
        vote = poll_svc.db.execute(
            select(PollVote).where(PollVote.poll_id == poll.id, PollVote.tg_user_id == 555)
        ).scalar_one()
        assert vote.choice == 0

    def test_updates_existing_vote(self, poll_svc, tournament):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, 555, choice=0)
        poll_svc.upsert_vote(poll.id, 555, choice=1)
        from sqlalchemy import select
        from core.models import PollVote
        votes = poll_svc.db.execute(
            select(PollVote).where(PollVote.poll_id == poll.id, PollVote.tg_user_id == 555)
        ).scalars().all()
        assert len(votes) == 1
        assert votes[0].choice == 1


# ── PollService.get_yes_voters_without_deck ──────────────────────────────────

class TestYesVotersWithoutDeck:
    def test_empty_when_no_poll(self, poll_svc, tournament):
        assert poll_svc.get_yes_voters_without_deck(tournament.id) == []

    def test_returns_yes_voter_without_deck(self, poll_svc, tournament, user_alice):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)  # пойду
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id in result

    def test_excludes_no_voter(self, poll_svc, tournament, user_alice):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=1)  # не пойду
        assert poll_svc.get_yes_voters_without_deck(tournament.id) == []

    def test_excludes_voter_who_has_deck(self, poll_svc, svc, tournament, user_alice, archetype_burn):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id not in result

    def test_includes_voter_registered_without_deck(self, poll_svc, svc, tournament, user_alice):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=None)
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id in result

    def test_mixed_voters(self, poll_svc, svc, tournament, user_alice, user_bob, archetype_burn):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)  # пойду, без колоды
        poll_svc.upsert_vote(poll.id, user_bob.tg_id, choice=0)    # пойду, с колодой
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_burn.id)
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id in result
        assert user_bob.tg_id not in result


# ── AdminHandler.handle_create_poll ─────────────────────────────────────────

class TestHandleCreatePoll:
    def test_not_admin_returns_error(self, admin_handler, tournament, user_alice):
        result = admin_handler.handle_create_poll(user_alice.tg_id, tournament.id)
        assert result.is_alert

    def test_returns_tournament_title(self, admin_handler, tournament, admin_user):
        result = admin_handler.handle_create_poll(admin_user.tg_id, tournament.id)
        assert not result.is_alert
        assert result.text == tournament.title

    def test_already_has_poll(self, admin_handler, poll_svc, tournament, admin_user):
        poll_svc.create_poll(tournament.id, 100, "p1", 1)
        result = admin_handler.handle_create_poll(admin_user.tg_id, tournament.id)
        assert result.is_alert
        assert "уже есть опрос" in result.text

    def test_tournament_not_found(self, admin_handler, admin_user):
        result = admin_handler.handle_create_poll(admin_user.tg_id, tournament_id=9999)
        assert result.is_alert
