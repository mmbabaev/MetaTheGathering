from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from bot.features import FeatureService
from bot.handlers.admin import AdminHandler
from bot.keyboards import Keyboards
from core import models
from core import models as m
from core.models import Tournament, TournamentStatus, Vote, VoteType, utc_now
from core.schemas import TournamentCreate
from services.errors import (
    ParticipantAlreadyRegistered,
    ParticipantNotFound,
    SelfVoteNotAllowed,
    TournamentAlreadyExists,
    TournamentInvalidState,
    TournamentNotFound,
    VotingNotAllowed,
)
from services.feature_flags import FeatureFlagService
from services.stats import StatsService
from services.tournament import CONFIRM_THRESHOLD, REJECT_THRESHOLD
from services.utils import get_tournament

# ===== Tournament lifecycle =====


class TestCreateTournament:
    def test_creates_with_correct_fields(self, svc):
        t = svc.create_tournament(TournamentCreate(title="Pauper Cup", chat_id=42, slug="pauper-cup"))
        assert t.title == "Pauper Cup"
        assert t.chat_id == 42
        assert t.slug == "pauper-cup"
        assert t.status == TournamentStatus.REGISTRATION

    def test_allows_second_active_tournament_in_same_chat(self, svc, tournament):
        second = svc.create_tournament(TournamentCreate(title="Another", chat_id=100))
        assert second.id != tournament.id
        assert [t.id for t in svc.list_active_tournaments_for_chat(100)] == [second.id, tournament.id]

    def test_raises_if_two_active_tournaments_exist(self, svc, tournament):
        svc.create_tournament(TournamentCreate(title="Second", chat_id=100))
        with pytest.raises(TournamentAlreadyExists):
            svc.create_tournament(TournamentCreate(title="Third", chat_id=100))

    def test_current_active_tournament_is_newest(self, svc, tournament):
        second = svc.create_tournament(TournamentCreate(title="Second", chat_id=100))
        assert svc.get_active_tournament_for_chat(100).id == second.id

    def test_allows_new_tournament_after_close(self, svc, tournament):
        svc.close_tournament(tournament.id)
        t2 = svc.create_tournament(TournamentCreate(title="Next", chat_id=100))
        assert t2.id != tournament.id


class TestTournamentLifecycle:
    def test_full_lifecycle(self, svc, tournament):
        t = svc.start_tournament(tournament.id)
        assert t.status == TournamentStatus.ONGOING
        assert t.started_at is not None

        t = svc.close_tournament(t.id)
        assert t.status == TournamentStatus.CLOSED
        assert t.ended_at is not None

    def test_close_directly_from_registration(self, svc, tournament):
        t = svc.close_tournament(tournament.id)
        assert t.status == TournamentStatus.CLOSED

    def test_start_from_ongoing_raises(self, svc, tournament):
        svc.start_tournament(tournament.id)
        with pytest.raises(TournamentInvalidState):
            svc.start_tournament(tournament.id)

    def test_invalid_transition_raises(self, svc, tournament):
        svc.close_tournament(tournament.id)
        with pytest.raises(TournamentInvalidState):
            svc.start_tournament(tournament.id)


# ===== Participants =====


class TestRegisterParticipant:
    def test_registers_successfully(self, svc, tournament, user_alice, archetype_burn):
        p = svc.register_participant(
            tournament_id=tournament.id,
            user_id=user_alice.id,
            archetype_id=archetype_burn.id,
        )
        assert p.tournament_id == tournament.id
        assert p.user_id == user_alice.id
        assert p.archetype_id == archetype_burn.id
        assert p.confirmed is False
        assert p.upvotes_count == 0
        assert p.downvotes_count == 0

    def test_raises_on_duplicate(self, svc, tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        with pytest.raises(ParticipantAlreadyRegistered):
            svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)

    def test_raises_when_registration_closed(self, svc, tournament, user_alice, archetype_burn):
        svc.start_tournament(tournament.id)
        with pytest.raises(TournamentInvalidState):
            svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)

    def test_added_by_admin_flag(self, svc, tournament, user_alice, archetype_burn):
        p = svc.register_participant(
            tournament_id=tournament.id,
            user_id=user_alice.id,
            archetype_id=archetype_burn.id,
            added_by_admin=True,
        )
        assert p.added_by_admin is True


class TestSetParticipantArchetype:
    def test_changes_archetype_and_resets_votes(
        self, svc, db, tournament, user_alice, user_bob, archetype_burn, archetype_affinity
    ):
        # Регистрируем alice и bob
        p_alice = svc.register_participant(
            tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)

        # Открываем голосование и голосуем
        svc.start_tournament(tournament.id)
        svc.cast_vote(
            tournament_id=tournament.id, participant_id=p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP
        )

        # Меняем архетип — голоса должны сброситься
        p_updated = svc.set_participant_archetype(participant_id=p_alice.id, archetype_id=archetype_affinity.id)
        assert p_updated.archetype_id == archetype_affinity.id
        assert p_updated.upvotes_count == 0
        assert p_updated.confirmed is False


# ===== Voting =====


class TestCastVote:
    @pytest.fixture(autouse=True)
    def setup_voting(self, svc, tournament, user_alice, user_bob, archetype_burn, archetype_affinity):
        """Регистрируем двух участников и открываем голосование."""
        self.p_alice = svc.register_participant(
            tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        self.p_bob = svc.register_participant(
            tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id
        )
        svc.start_tournament(tournament.id)

    def test_upvote_increments_counter(self, svc, tournament, user_bob):
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.UP,
        )
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 1
        assert p.downvotes_count == 0

    def test_downvote_increments_counter(self, svc, tournament, user_bob):
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.DOWN,
        )
        p = svc._get_participant(self.p_alice.id)
        assert p.downvotes_count == 1
        assert p.upvotes_count == 0

    def test_self_vote_raises(self, svc, tournament, user_alice):
        with pytest.raises(SelfVoteNotAllowed):
            svc.cast_vote(
                tournament_id=tournament.id,
                participant_id=self.p_alice.id,
                voter_user_id=user_alice.id,
                vote_type=VoteType.UP,
            )

    def test_vote_outside_ongoing_tournament_raises(self, svc, db, tournament, user_bob):
        # Закрываем турнир — legacy-голосование недоступно
        t_orm = db.get(Tournament, tournament.id)
        t_orm.status = TournamentStatus.CLOSED
        db.commit()
        with pytest.raises(TournamentInvalidState):
            svc.cast_vote(
                tournament_id=tournament.id,
                participant_id=self.p_alice.id,
                voter_user_id=user_bob.id,
                vote_type=VoteType.UP,
            )

    def test_vote_during_registration_raises(self, svc, db, tournament, user_bob):
        t_orm = db.get(Tournament, tournament.id)
        t_orm.status = TournamentStatus.REGISTRATION
        db.commit()
        with pytest.raises(TournamentInvalidState):
            svc.cast_vote(
                tournament_id=tournament.id,
                participant_id=self.p_alice.id,
                voter_user_id=user_bob.id,
                vote_type=VoteType.UP,
            )

    def test_vote_change_updates_counters(self, svc, db, tournament, user_bob):
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.UP,
        )
        # Сдвигаем created_at голоса назад, чтобы обойти cooldown
        vote = db.query(Vote).filter_by(participant_id=self.p_alice.id, voter_id=user_bob.id).first()
        vote.created_at = utc_now() - timedelta(seconds=60)
        db.commit()

        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.DOWN,
            apply_cooldown=True,
        )
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 0
        assert p.downvotes_count == 1

    def test_vote_change_cooldown_raises(self, svc, tournament, user_bob):
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.UP,
        )
        # Сразу меняем голос — cooldown не прошёл
        with pytest.raises(VotingNotAllowed):
            svc.cast_vote(
                tournament_id=tournament.id,
                participant_id=self.p_alice.id,
                voter_user_id=user_bob.id,
                vote_type=VoteType.DOWN,
                apply_cooldown=True,
            )

    def test_same_vote_twice_is_idempotent(self, svc, tournament, user_bob):
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.UP,
        )
        # apply_cooldown=False чтобы дойти до проверки идемпотентности
        svc.cast_vote(
            tournament_id=tournament.id,
            participant_id=self.p_alice.id,
            voter_user_id=user_bob.id,
            vote_type=VoteType.UP,
            apply_cooldown=False,
        )
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 1  # не увеличился дважды


# ===== Confirmation thresholds =====


class TestConfirmationThreshold:
    def _make_voters(self, svc, user_svc, arch_svc, tournament, count):
        voters = []
        for i in range(count):
            u = user_svc.get_or_create(tg_id=2000 + i, username=f"voter{i}")
            archetype = arch_svc.get_or_create_by_name(f"Deck{i}")
            svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=archetype.id)
            voters.append(u)
        return voters

    def test_confirmed_after_enough_upvotes(self, svc, user_svc, arch_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, arch_svc, tournament, CONFIRM_THRESHOLD)
        svc.start_tournament(tournament.id)

        for v in voters:
            svc.cast_vote(tournament_id=tournament.id, participant_id=p.id, voter_user_id=v.id, vote_type=VoteType.UP)

        participant = svc._get_participant(p.id)
        assert participant.confirmed is True

    def test_not_confirmed_below_threshold(self, svc, user_svc, arch_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, arch_svc, tournament, CONFIRM_THRESHOLD - 1)
        svc.start_tournament(tournament.id)

        for v in voters:
            svc.cast_vote(tournament_id=tournament.id, participant_id=p.id, voter_user_id=v.id, vote_type=VoteType.UP)

        participant = svc._get_participant(p.id)
        assert participant.confirmed is False

    def test_rejected_after_enough_downvotes(self, svc, user_svc, arch_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, arch_svc, tournament, REJECT_THRESHOLD)
        svc.start_tournament(tournament.id)

        for v in voters:
            svc.cast_vote(tournament_id=tournament.id, participant_id=p.id, voter_user_id=v.id, vote_type=VoteType.DOWN)

        participant = svc._get_participant(p.id)
        assert participant.confirmed is False


# ===== get_or_create helpers =====


class TestGetOrCreate:
    def test_get_or_create_user_creates_new(self, user_svc):
        u = user_svc.get_or_create(tg_id=9999, username="newuser", first_name="New")
        assert u.tg_id == 9999
        assert u.username == "newuser"

    def test_get_or_create_user_returns_existing(self, user_svc):
        u1 = user_svc.get_or_create(tg_id=9999, username="newuser")
        u2 = user_svc.get_or_create(tg_id=9999, username="newuser")
        assert u1.id == u2.id

    def test_get_or_create_archetype_creates_new(self, svc, arch_svc):
        a = arch_svc.get_or_create_by_name("Bogles")
        assert a.name == "Bogles"

    def test_get_or_create_archetype_returns_existing(self, svc, arch_svc):
        a1 = arch_svc.get_or_create_by_name("Bogles")
        a2 = arch_svc.get_or_create_by_name("Bogles")
        assert a1.id == a2.id


# ===== list_participants =====


class TestListParticipants:
    def test_returns_all_participants(self, svc, tournament, user_alice, user_bob, archetype_burn, archetype_affinity):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)
        participants = svc.list_participants_for_tournament(tournament.id)
        assert len(participants) == 2

    def test_includes_user_and_archetype(self, svc, tournament, user_alice, archetype_burn):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        participants = svc.list_participants_for_tournament(tournament.id)
        p = participants[0]
        assert p.user.tg_id == user_alice.tg_id
        assert p.archetype.name == "Burn"

    def test_empty_for_no_participants(self, svc, tournament):
        participants = svc.list_participants_for_tournament(tournament.id)
        assert participants == []


# ===== reset_votes =====


class TestResetVotes:
    def test_reset_clears_all_votes(
        self, svc, db, tournament, user_alice, user_bob, archetype_burn, archetype_affinity
    ):
        p_alice = svc.register_participant(
            tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id
        )
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)
        svc.start_tournament(tournament.id)
        svc.cast_vote(
            tournament_id=tournament.id, participant_id=p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP
        )

        svc.reset_votes_for_participant(p_alice.id)
        p = svc._get_participant(p_alice.id)
        assert p.upvotes_count == 0
        assert p.downvotes_count == 0
        assert p.confirmed is False


# ===== Meta aggregation =====


class TestGetTournamentMeta:
    def test_meta_aggregates_by_archetype(
        self, db, svc, user_svc, tournament, user_alice, user_bob, archetype_burn, archetype_affinity
    ):
        u3 = user_svc.get_or_create(tg_id=1003, username="carol")
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=u3.id, archetype_id=archetype_affinity.id)

        meta = StatsService(db).get_tournament_meta(tournament.id)
        by_name = {row.archetype_name: row for row in meta}

        assert by_name["Burn"].count == 2
        assert by_name["Affinity"].count == 1

    def test_meta_empty_for_no_participants(self, db, svc, tournament):
        meta = StatsService(db).get_tournament_meta(tournament.id)
        assert meta == []


class TestListArchetypesForUser:
    def test_unknown_user_returns_top10_alphabetically(self, svc, arch_svc):
        for name in ("Burn", "Affinity", "Elves"):
            arch_svc.get_or_create_by_name(name)
        result = arch_svc.list_archetypes_for_user(tg_id=9999)
        names = [a.name for a in result]
        assert names == sorted(names)
        assert len(result) <= 10

    def test_recent_choice_comes_first(self, svc, tournament, user_alice, archetype_burn, archetype_affinity, arch_svc):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = arch_svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert result[0].name == "Burn"

    def test_most_recent_choice_wins(self, svc, db, user_alice, archetype_burn, archetype_affinity, arch_svc):
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=1))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=2))
        svc.register_participant(tournament_id=t1.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        # Make t2 participant appear newer
        p2 = m.Participant(
            tournament_id=t2.id,
            user_id=user_alice.id,
            archetype_id=archetype_affinity.id,
            added_by_admin=False,
            confirmed=False,
            upvotes_count=0,
            downvotes_count=0,
            created_at=utc_now() + timedelta(seconds=1),
            updated_at=utc_now(),
        )
        db.add(p2)
        db.commit()
        result = arch_svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert result[0].name == "Affinity"
        assert result[1].name == "Burn"

    def test_deduplicates_repeated_choices(self, svc, db, user_alice, archetype_burn, arch_svc):
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=1))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=2))
        svc.register_participant(tournament_id=t1.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=t2.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = arch_svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert [a.name for a in result].count("Burn") == 1

    def test_caps_at_total(self, svc, arch_svc):
        for i in range(15):
            arch_svc.get_or_create_by_name(f"Arch{i:02d}")
        result = arch_svc.list_archetypes_for_user(tg_id=9999, total=10)
        assert len(result) == 10


# ===== List methods =====


class TestListTournamentsForChat:
    def test_returns_all_including_closed(self, svc):
        t1 = svc.create_tournament(TournamentCreate(title="A", chat_id=300, slug="a300"))
        svc.close_tournament(t1.id)
        t2 = svc.create_tournament(TournamentCreate(title="B", chat_id=300, slug="b300"))
        result = svc.list_tournaments_for_chat(300)
        ids = {t.id for t in result}
        assert t1.id in ids
        assert t2.id in ids

    def test_excludes_other_chats(self, svc):
        svc.create_tournament(TournamentCreate(title="A", chat_id=301, slug="a301"))
        svc.create_tournament(TournamentCreate(title="B", chat_id=302, slug="b302"))
        result = svc.list_tournaments_for_chat(301)
        assert all(t.chat_id == 301 for t in result)

    def test_respects_limit(self, svc):
        t1 = svc.create_tournament(TournamentCreate(title="A", chat_id=303, slug="a303"))
        svc.close_tournament(t1.id)
        svc.create_tournament(TournamentCreate(title="B", chat_id=303, slug="b303"))
        result = svc.list_tournaments_for_chat(303, limit=1)
        assert len(result) == 1

    def test_empty_for_unknown_chat(self, svc):
        assert svc.list_tournaments_for_chat(99999) == []


class TestListActiveTournamentsForChat:
    def test_excludes_closed(self, svc):
        t = svc.create_tournament(TournamentCreate(title="A", chat_id=310, slug="a310"))
        svc.close_tournament(t.id)
        assert svc.list_active_tournaments_for_chat(310) == []

    def test_includes_registration_and_voting(self, svc):
        svc.create_tournament(TournamentCreate(title="A", chat_id=311, slug="a311"))
        result = svc.list_active_tournaments_for_chat(311)
        assert len(result) == 1
        assert result[0].status == TournamentStatus.REGISTRATION

    def test_empty_for_unknown_chat(self, svc):
        assert svc.list_active_tournaments_for_chat(99998) == []


# ===== open_registration =====


class TestOpenRegistration:
    def test_sets_status_to_registration(self, svc):
        t = svc.create_tournament(TournamentCreate(title="A", chat_id=320, slug="a320"))
        t = svc.start_tournament(t.id)
        assert t.status == TournamentStatus.ONGOING
        t = svc.open_registration(t.id)
        assert t.status == TournamentStatus.REGISTRATION
        assert t.registration_open_at is not None


# ===== reopen_tournament =====


class TestReopenTournament:
    def test_closed_tournament_becomes_registration(self, svc):
        t = svc.create_tournament(TournamentCreate(title="R", chat_id=330, slug="r330"))
        svc.close_tournament(t.id)
        t = svc.reopen_tournament(t.id)
        assert t.status == TournamentStatus.REGISTRATION
        assert t.ended_at is None
        assert t.registration_open_at is not None

    def test_reopened_is_active_for_chat(self, svc):
        t = svc.create_tournament(TournamentCreate(title="R2", chat_id=331, slug="r331"))
        svc.close_tournament(t.id)
        assert svc.get_active_tournament_for_chat(331) is None
        svc.reopen_tournament(t.id)
        active = svc.get_active_tournament_for_chat(331)
        assert active is not None
        assert active.id == t.id

    def test_rejects_non_closed_tournament(self, svc):
        t = svc.create_tournament(TournamentCreate(title="R3", chat_id=332, slug="r332"))
        with pytest.raises(TournamentInvalidState):
            svc.reopen_tournament(t.id)

    def test_allows_reopen_when_chat_has_one_active(self, svc):
        old = svc.create_tournament(TournamentCreate(title="Old", chat_id=333, slug="o333"))
        svc.close_tournament(old.id)
        new = svc.create_tournament(TournamentCreate(title="New", chat_id=333, slug="n333"))
        reopened = svc.reopen_tournament(old.id)
        assert [t.id for t in svc.list_active_tournaments_for_chat(333)] == [new.id, reopened.id]

    def test_rejects_reopen_when_chat_already_has_two_active(self, svc):
        old = svc.create_tournament(TournamentCreate(title="Old", chat_id=336, slug="o336"))
        svc.close_tournament(old.id)
        svc.create_tournament(TournamentCreate(title="New 1", chat_id=336, slug="n336-1"))
        svc.create_tournament(TournamentCreate(title="New 2", chat_id=336, slug="n336-2"))
        with pytest.raises(TournamentAlreadyExists):
            svc.reopen_tournament(old.id)

    def test_other_chat_active_does_not_block(self, svc):
        t = svc.create_tournament(TournamentCreate(title="A", chat_id=334, slug="a334"))
        svc.close_tournament(t.id)
        svc.create_tournament(TournamentCreate(title="B", chat_id=335, slug="b335"))
        assert svc.reopen_tournament(t.id).status == TournamentStatus.REGISTRATION

    def test_missing_tournament_raises(self, svc):
        with pytest.raises(TournamentNotFound):
            svc.reopen_tournament(999999)


# ===== _get_participant error path =====


class TestGetParticipantNotFound:
    def test_raises_on_missing_participant(self, svc):
        with pytest.raises(ParticipantNotFound):
            svc._get_participant(99999)


# ===== cast_vote edge cases =====


class TestCastVoteEdgeCases:
    @pytest.fixture
    def voting_setup(self, svc, user_svc, arch_svc):
        """Two chats each with their own ongoing tournament."""
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=400, slug="t1"))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=401, slug="t2"))
        ua = user_svc.get_or_create(tg_id=4001, username="ua", first_name="UA")
        ub = user_svc.get_or_create(tg_id=4002, username="ub", first_name="UB")
        arch = arch_svc.get_or_create_by_name("Burn")
        # Register participant before starting tournaments
        p = svc.register_participant(tournament_id=t1.id, user_id=ua.id, archetype_id=arch.id)
        svc.start_tournament(t1.id)
        svc.start_tournament(t2.id)
        return t1, t2, ua, ub, arch, p

    def test_participant_in_wrong_tournament_raises(self, svc, voting_setup):
        t1, t2, ua, ub, arch, p = voting_setup
        # p belongs to t1 but we vote against t2
        with pytest.raises(VotingNotAllowed):
            svc.cast_vote(
                tournament_id=t2.id,
                participant_id=p.id,
                voter_user_id=ub.id,
                vote_type=VoteType.UP,
            )

    def test_nonexistent_voter_raises(self, svc, voting_setup):
        t1, t2, ua, ub, arch, p = voting_setup
        with pytest.raises(VotingNotAllowed):
            svc.cast_vote(
                tournament_id=t1.id,
                participant_id=p.id,
                voter_user_id=99999,  # does not exist
                vote_type=VoteType.UP,
            )

    def test_change_vote_down_to_up(self, svc, voting_setup):
        t1, t2, ua, ub, arch, p = voting_setup
        # First vote: DOWN
        svc.cast_vote(
            tournament_id=t1.id,
            participant_id=p.id,
            voter_user_id=ub.id,
            vote_type=VoteType.DOWN,
            apply_cooldown=False,
        )
        # Change to UP
        result = svc.cast_vote(
            tournament_id=t1.id,
            participant_id=p.id,
            voter_user_id=ub.id,
            vote_type=VoteType.UP,
            apply_cooldown=False,
        )
        assert result.vote_type == VoteType.UP
        # Reload participant to verify counters
        part = svc.db.execute(select(m.Participant).where(m.Participant.id == p.id)).scalar_one()
        assert part.downvotes_count == 0
        assert part.upvotes_count == 1


# ===== bulk_add_participants =====


class TestBulkAddParticipants:
    @pytest.fixture
    def tournament(self, svc):
        return svc.create_tournament(TournamentCreate(title="Bulk Test", chat_id=500, slug="bulk"))

    @pytest.fixture
    def users(self, user_svc):
        a = user_svc.get_or_create(tg_id=5001, username="a", first_name="Alice")
        b = user_svc.get_or_create(tg_id=5002, username="b", first_name="Bob")
        return a, b

    def test_adds_participants_without_archetype(self, svc, tournament, users):
        alice, bob = users
        results = svc.bulk_add_participants(tournament.id, [(alice.id, "Alice"), (bob.id, "Bob")])
        assert len(results) == 2
        assert all(status == "added" for _, status in results)
        assert svc.get_participant(tournament.id, alice.id) is not None
        assert svc.get_participant(tournament.id, bob.id) is not None

    def test_archetype_is_none(self, svc, tournament, users):
        alice, _ = users
        svc.bulk_add_participants(tournament.id, [(alice.id, "Alice")])
        p = svc.get_participant(tournament.id, alice.id)
        assert p.archetype_id is None

    def test_added_by_admin_flag(self, svc, tournament, users):
        alice, _ = users
        svc.bulk_add_participants(tournament.id, [(alice.id, "Alice")])
        p = svc.get_participant(tournament.id, alice.id)
        assert p.added_by_admin is True

    def test_skips_already_registered(self, svc, tournament, users, archetype_burn):
        alice, _ = users
        svc.register_participant(tournament_id=tournament.id, user_id=alice.id, archetype_id=archetype_burn.id)
        results = svc.bulk_add_participants(tournament.id, [(alice.id, "Alice")])
        assert results[0] == ("Alice", "already_registered")

    def test_skips_duplicate_in_same_batch(self, svc, tournament, users):
        alice, _ = users
        results = svc.bulk_add_participants(
            tournament.id,
            [(alice.id, "Alice"), (alice.id, "Alice again")],
        )
        assert results[0] == ("Alice", "added")
        assert results[1] == ("Alice again", "already_registered")

    def test_mixed_new_and_existing(self, svc, tournament, users, archetype_burn):
        alice, bob = users
        svc.register_participant(tournament_id=tournament.id, user_id=alice.id, archetype_id=archetype_burn.id)
        results = svc.bulk_add_participants(tournament.id, [(alice.id, "Alice"), (bob.id, "Bob")])
        statuses = dict(results)
        assert statuses["Alice"] == "already_registered"
        assert statuses["Bob"] == "added"

    def test_raises_when_tournament_not_found(self, svc, users):
        alice, _ = users
        with pytest.raises(TournamentNotFound):
            svc.bulk_add_participants(99999, [(alice.id, "Alice")])

    def test_raises_when_registration_closed(self, svc, tournament, users):
        alice, _ = users
        svc.close_tournament(tournament.id)
        with pytest.raises(TournamentInvalidState):
            svc.bulk_add_participants(tournament.id, [(alice.id, "Alice")])

    def test_empty_entries_returns_empty_list(self, svc, tournament):
        results = svc.bulk_add_participants(tournament.id, [])
        assert results == []


# ===== UserService.get_or_create_by_name =====


class TestGetOrCreateByName:
    def test_creates_user_with_first_and_last_name(self, user_svc, db):
        user, created = user_svc.get_or_create_by_name("Иван", "Иванов")
        db.commit()
        assert created is True
        assert user.first_name == "Иван"
        assert user.last_name == "Иванов"
        assert user.tg_id < 0

    def test_creates_user_with_first_name_only(self, user_svc, db):
        user, created = user_svc.get_or_create_by_name("Мария")
        db.commit()
        assert created is True
        assert user.first_name == "Мария"
        assert user.last_name is None

    def test_finds_existing_user(self, user_svc, db):
        user_svc.get_or_create_by_name("Пётр", "Петров")
        db.commit()
        user2, created = user_svc.get_or_create_by_name("Пётр", "Петров")
        db.commit()
        assert created is False
        assert user2.first_name == "Пётр"

    def test_placeholder_tg_ids_decrement(self, user_svc, db):
        u1, _ = user_svc.get_or_create_by_name("Первый")
        db.commit()
        u2, _ = user_svc.get_or_create_by_name("Второй")
        db.commit()
        assert u2.tg_id < u1.tg_id

    def test_same_first_name_different_last_name_creates_two(self, user_svc, db):
        u1, _ = user_svc.get_or_create_by_name("Иван", "Иванов")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("Иван", "Петров")
        db.commit()
        assert created is True
        assert u1.id != u2.id

    def test_first_name_only_vs_with_last_name_are_different(self, user_svc, db):
        u1, _ = user_svc.get_or_create_by_name("Иван")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("Иван", "Иванов")
        db.commit()
        assert created is True
        assert u1.id != u2.id

    # --- Гибкий поиск (регистр, ё/е, порядок имён) ---

    def test_case_insensitive_match(self, user_svc, db):
        """'иванов Иван' находит 'Иванов' 'Иван'."""
        u1, _ = user_svc.get_or_create_by_name("Иванов", "Иван")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("иванов", "иван")
        db.commit()
        assert created is False
        assert u1.id == u2.id

    def test_yo_ye_normalization(self, user_svc, db):
        """'Семен' находит 'Семён' (ё→е нормализация)."""
        u1, _ = user_svc.get_or_create_by_name("Семён", "Фёдоров")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("Семен", "Федоров")
        db.commit()
        assert created is False
        assert u1.id == u2.id

    def test_swapped_name_order_finds_existing(self, user_svc, db):
        """'Антон Ильин' находит 'Ильин Антон' (порядок Фамилия Имя → Имя Фамилия)."""
        u1, _ = user_svc.get_or_create_by_name("Ильин", "Антон")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("Антон", "Ильин")
        db.commit()
        assert created is False
        assert u1.id == u2.id

    def test_two_word_first_name_matches_split_aetherhub_name(self, user_svc, db):
        """Telegram may put the whole display name into first_name and leave last_name empty."""
        real = user_svc.get_or_create(tg_id=12345, first_name="Антон Ильин")
        found, created = user_svc.get_or_create_by_name("Антон", "Ильин")
        db.commit()
        assert created is False
        assert found.id == real.id

    def test_prefers_user_with_deck_history(self, user_svc, db, svc, arch_svc):
        """Когда два совпадения — возвращает того, у кого есть история колод."""
        # Два пользователя с одинаковыми именами (разный порядок слов)
        u_no_hist, _ = user_svc.get_or_create_by_name("Антон", "Ильин")
        db.commit()
        u_with_hist, _ = user_svc.get_or_create_by_name("Ильин", "Антон")
        db.commit()

        # Даём u_with_hist историю колод
        arch = arch_svc.get_or_create_by_name("Burn")
        db.add(models.UserDeckHistory(user_id=u_with_hist.id, archetype_id=arch.id, source="test"))
        db.commit()

        # Поиск должен вернуть u_with_hist
        found, created = user_svc.get_or_create_by_name("Антон", "Ильин")
        assert created is False
        assert found.id == u_with_hist.id

    def test_swapped_order_case_insensitive(self, user_svc, db):
        """Комбинация: нижний регистр + обратный порядок."""
        u1, _ = user_svc.get_or_create_by_name("Левитина", "Мария")
        db.commit()
        u2, created = user_svc.get_or_create_by_name("мария", "левитина")
        db.commit()
        assert created is False
        assert u1.id == u2.id

    def test_bulk_add_uses_flexible_search(self, user_svc, db, svc, arch_svc):
        """handle_bulk_add_by_name находит игрока даже при перестановке имени и фамилии."""
        # Создаём пользователя в DataLens-порядке (Фамилия Имя)
        u, _ = user_svc.get_or_create_by_name("Ильин", "Антон")
        db.commit()

        # Назначаем ему историю (чтобы убедиться что нашли правильного)
        arch = arch_svc.get_or_create_by_name("Elves")
        db.add(m.UserDeckHistory(user_id=u.id, archetype_id=arch.id, source="test"))
        db.commit()

        # Турнир
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=9999))

        ff_svc = FeatureFlagService(db)
        handler = AdminHandler(svc, user_svc, arch_svc, Keyboards(), FeatureService(ff_svc))

        # Добавляем в порядке Фамилия Имя (как вводит оператор)
        with patch("services.user.settings") as mock_settings:
            mock_settings.admin_ids = [0]
            result = handler.handle_bulk_add_by_name(tg_id=0, tournament_id=t.id, names=["Ильин Антон"])
        assert "✅ Ильин Антон" in result.text

        # Участник должен быть привязан к правильному пользователю (с историей)
        participant = svc.get_participant(t.id, u.id)
        assert participant is not None, "Участник не связан с правильным пользователем"


class TestSetAetherhubUrl:
    def test_stores_url(self, svc, tournament):
        url = "https://aetherhub.com/Tourney/RoundTourney/12345"
        svc.set_aetherhub_url(tournament.id, url)
        t = get_tournament(svc.db, tournament.id)
        assert t.aetherhub_url == url

    def test_overwrites_existing_url(self, svc, tournament):
        svc.set_aetherhub_url(tournament.id, "https://aetherhub.com/old")
        svc.set_aetherhub_url(tournament.id, "https://aetherhub.com/new")
        t = get_tournament(svc.db, tournament.id)
        assert t.aetherhub_url == "https://aetherhub.com/new"

    def test_tournament_read_schema_includes_url(self, svc, tournament):
        url = "https://aetherhub.com/Tourney/RoundTourney/99"
        svc.set_aetherhub_url(tournament.id, url)
        tournaments = svc.list_all_active_tournaments()
        match = next(t for t in tournaments if t.id == tournament.id)
        assert match.aetherhub_url == url


class TestDeckRecorders:
    def test_lists_recorders_with_2plus_sorted_by_count(self, svc, user_svc, arch_svc):
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
        arch = arch_svc.get_or_create_by_name("Burn")
        user_svc.get_or_create(tg_id=999, username="scorer", first_name="Анна", last_name="Волкова")
        loner = user_svc.get_or_create(tg_id=888, username="solo", first_name="Пётр", last_name="Иванов")

        # scorer (tg 999) записал 3 колоды за троих; loner (tg 888) — только 1 свою
        for tg in (1, 2, 3):
            u = user_svc.get_or_create(tg_id=tg, first_name=f"P{tg}")
            svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=arch.id, deck_added_by_tg_id=999)
        svc.register_participant(tournament_id=t.id, user_id=loner.id, archetype_id=arch.id, deck_added_by_tg_id=888)

        recs = svc.get_deck_recorders(t.id, min_count=2)
        assert [(r.username, r.count) for r in recs] == [("scorer", 3)]
        assert recs[0].last_name == "Волкова" and recs[0].first_name == "Анна"

    def test_empty_when_nobody_reaches_min(self, svc, user_svc, arch_svc):
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
        arch = arch_svc.get_or_create_by_name("Burn")
        u = user_svc.get_or_create(tg_id=1, first_name="P1")
        svc.register_participant(tournament_id=t.id, user_id=u.id, archetype_id=arch.id, deck_added_by_tg_id=1)
        assert svc.get_deck_recorders(t.id, min_count=2) == []
