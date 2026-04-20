"""Tests for PollService and AdminHandler.handle_create_poll."""

from datetime import timedelta

import pytest

from services.poll import PollService, DM_COOLDOWN_SECONDS
from services.user import UserService
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from core.models import utc_now
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

    def test_get_latest_poll_for_chat(self, poll_svc, tournament):
        poll_svc.create_poll(tournament.id, 100, "p_only", 1)
        latest = poll_svc.get_latest_poll_for_chat(100)
        assert latest is not None
        assert latest.tg_poll_id == "p_only"

    def test_get_latest_poll_for_chat_no_poll(self, poll_svc):
        assert poll_svc.get_latest_poll_for_chat(999) is None


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

    def test_cross_tournament_poll(self, poll_svc, svc, db, user_alice):
        """Голоса из старого опроса, колода проверяется по новому турниру."""
        from core.schemas import TournamentCreate
        old_t = svc.create_tournament(TournamentCreate(title="Old", chat_id=100))
        old_poll = poll_svc.create_poll(old_t.id, 100, "old_p", 1)
        poll_svc.upsert_vote(old_poll.id, user_alice.tg_id, choice=0)
        # Alice has deck in old tournament
        svc.register_participant(tournament_id=old_t.id, user_id=user_alice.id, archetype_id=None)
        # Close old, create new tournament
        svc.close_tournament(old_t.id)
        new_t = svc.create_tournament(TournamentCreate(title="New", chat_id=100))
        # No poll for new tournament — use old poll_id explicitly
        result = poll_svc.get_yes_voters_without_deck(new_t.id, poll_id=old_poll.id)
        # Alice voted yes in old poll and has NO deck in NEW tournament → should be notified
        assert user_alice.tg_id in result

    def test_mixed_voters(self, poll_svc, svc, tournament, user_alice, user_bob, archetype_burn):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)  # пойду, без колоды
        poll_svc.upsert_vote(poll.id, user_bob.tg_id, choice=0)    # пойду, с колодой
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_burn.id)
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id in result
        assert user_bob.tg_id not in result


# ── PollService.mark_notified + DM cooldown ─────────────────────────────────

class TestDmCooldown:
    def test_mark_notified_sets_last_dm_at(self, poll_svc, svc, tournament, user_alice):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        poll_svc.mark_notified(tournament.id, [user_alice.tg_id])
        from sqlalchemy import select
        from core.models import Participant
        p = poll_svc.db.execute(
            select(Participant).where(
                Participant.tournament_id == tournament.id,
                Participant.user_id == user_alice.id,
            )
        ).scalar_one()
        assert p.last_dm_at is not None

    def test_recently_notified_excluded(self, poll_svc, svc, tournament, user_alice):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        poll_svc.mark_notified(tournament.id, [user_alice.tg_id])
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id not in result

    def test_old_notification_not_excluded(self, poll_svc, svc, tournament, user_alice):
        poll = poll_svc.create_poll(tournament.id, 100, "p1", 1)
        poll_svc.upsert_vote(poll.id, user_alice.tg_id, choice=0)
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id)
        # Simulate old notification
        from sqlalchemy import select
        from core.models import Participant
        p = poll_svc.db.execute(
            select(Participant).where(Participant.tournament_id == tournament.id)
        ).scalar_one()
        p.last_dm_at = utc_now() - timedelta(seconds=DM_COOLDOWN_SECONDS + 60)
        poll_svc.db.commit()
        result = poll_svc.get_yes_voters_without_deck(tournament.id)
        assert user_alice.tg_id in result

    def test_mark_notified_no_ids_is_noop(self, poll_svc, tournament):
        poll_svc.mark_notified(tournament.id, [])  # should not raise


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
