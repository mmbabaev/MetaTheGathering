from datetime import timedelta

import pytest

from core.models import TournamentStatus, VoteType, utc_now
from core.schemas import TournamentCreate
from services.errors import (
    TournamentAlreadyExists,
    TournamentInvalidState,
    ParticipantAlreadyRegistered,
    SelfVoteNotAllowed,
    VotingNotAllowed,
)
from services.tournament import CONFIRM_THRESHOLD, REJECT_THRESHOLD


# ===== Tournament lifecycle =====

class TestCreateTournament:
    def test_creates_with_correct_fields(self, svc):
        t = svc.create_tournament(TournamentCreate(title="Pauper Cup", chat_id=42, slug="pauper-cup"))
        assert t.title == "Pauper Cup"
        assert t.chat_id == 42
        assert t.slug == "pauper-cup"
        assert t.status == TournamentStatus.REGISTRATION

    def test_raises_if_active_tournament_exists(self, svc, tournament):
        with pytest.raises(TournamentAlreadyExists):
            svc.create_tournament(TournamentCreate(title="Another", chat_id=100))

    def test_allows_new_tournament_after_close(self, svc, tournament):
        svc.close_tournament(tournament.id)
        t2 = svc.create_tournament(TournamentCreate(title="Next", chat_id=100))
        assert t2.id != tournament.id


class TestTournamentLifecycle:
    def test_full_lifecycle(self, svc, tournament):
        t = svc.start_tournament(tournament.id)
        assert t.status == TournamentStatus.ONGOING

        t = svc.open_voting(t.id)
        assert t.status == TournamentStatus.VOTING

        t = svc.close_tournament(t.id)
        assert t.status == TournamentStatus.CLOSED
        assert t.ended_at is not None

    def test_open_voting_from_registration(self, svc, tournament):
        # Можно перейти в VOTING прямо из REGISTRATION (пропустив ONGOING)
        t = svc.open_voting(tournament.id)
        assert t.status == TournamentStatus.VOTING

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
    def test_changes_archetype_and_resets_votes(self, svc, db, tournament, user_alice, user_bob, archetype_burn, archetype_affinity):
        # Регистрируем alice и bob
        p_alice = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)

        # Открываем голосование и голосуем
        svc.open_voting(tournament.id)
        svc.cast_vote(tournament_id=tournament.id, participant_id=p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)

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
        self.p_alice = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        self.p_bob = svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)
        svc.open_voting(tournament.id)

    def test_upvote_increments_counter(self, svc, tournament, user_bob):
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 1
        assert p.downvotes_count == 0

    def test_downvote_increments_counter(self, svc, tournament, user_bob):
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.DOWN)
        p = svc._get_participant(self.p_alice.id)
        assert p.downvotes_count == 1
        assert p.upvotes_count == 0

    def test_self_vote_raises(self, svc, tournament, user_alice):
        with pytest.raises(SelfVoteNotAllowed):
            svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_alice.id, vote_type=VoteType.UP)

    def test_vote_outside_voting_phase_raises(self, svc, db, tournament, user_bob):
        # Закрываем турнир — голосование недоступно
        from core.models import Tournament
        t_orm = db.get(Tournament, tournament.id)
        t_orm.status = TournamentStatus.CLOSED
        db.commit()
        with pytest.raises(TournamentInvalidState):
            svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)

    def test_vote_change_updates_counters(self, svc, db, tournament, user_bob):
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)
        # Сдвигаем created_at голоса назад, чтобы обойти cooldown
        from core.models import Vote
        vote = db.query(Vote).filter_by(participant_id=self.p_alice.id, voter_id=user_bob.id).first()
        vote.created_at = utc_now() - timedelta(seconds=60)
        db.commit()

        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.DOWN, apply_cooldown=True)
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 0
        assert p.downvotes_count == 1

    def test_vote_change_cooldown_raises(self, svc, tournament, user_bob):
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)
        # Сразу меняем голос — cooldown не прошёл
        with pytest.raises(VotingNotAllowed):
            svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.DOWN, apply_cooldown=True)

    def test_same_vote_twice_is_idempotent(self, svc, tournament, user_bob):
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)
        # apply_cooldown=False чтобы дойти до проверки идемпотентности
        svc.cast_vote(tournament_id=tournament.id, participant_id=self.p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP, apply_cooldown=False)
        p = svc._get_participant(self.p_alice.id)
        assert p.upvotes_count == 1  # не увеличился дважды


# ===== Confirmation thresholds =====

class TestConfirmationThreshold:
    def _make_voters(self, svc, user_svc, tournament, count):
        voters = []
        for i in range(count):
            u = user_svc.get_or_create(tg_id=2000 + i, username=f"voter{i}")
            archetype = svc.get_or_create_archetype_by_name(f"Deck{i}")
            svc.register_participant(tournament_id=tournament.id, user_id=u.id, archetype_id=archetype.id)
            voters.append(u)
        return voters

    def test_confirmed_after_enough_upvotes(self, svc, user_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, tournament, CONFIRM_THRESHOLD)
        svc.open_voting(tournament.id)

        for v in voters:
            svc.cast_vote(tournament_id=tournament.id, participant_id=p.id, voter_user_id=v.id, vote_type=VoteType.UP)

        participant = svc._get_participant(p.id)
        assert participant.confirmed is True

    def test_not_confirmed_below_threshold(self, svc, user_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, tournament, CONFIRM_THRESHOLD - 1)
        svc.open_voting(tournament.id)

        for v in voters:
            svc.cast_vote(tournament_id=tournament.id, participant_id=p.id, voter_user_id=v.id, vote_type=VoteType.UP)

        participant = svc._get_participant(p.id)
        assert participant.confirmed is False

    def test_rejected_after_enough_downvotes(self, svc, user_svc, db, tournament, user_alice, archetype_burn):
        p = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        voters = self._make_voters(svc, user_svc, tournament, REJECT_THRESHOLD)
        svc.open_voting(tournament.id)

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

    def test_get_or_create_archetype_creates_new(self, svc):
        a = svc.get_or_create_archetype_by_name("Bogles")
        assert a.name == "Bogles"

    def test_get_or_create_archetype_returns_existing(self, svc):
        a1 = svc.get_or_create_archetype_by_name("Bogles")
        a2 = svc.get_or_create_archetype_by_name("Bogles")
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
    def test_reset_clears_all_votes(self, svc, db, tournament, user_alice, user_bob, archetype_burn, archetype_affinity):
        p_alice = svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_affinity.id)
        svc.open_voting(tournament.id)
        svc.cast_vote(tournament_id=tournament.id, participant_id=p_alice.id, voter_user_id=user_bob.id, vote_type=VoteType.UP)

        svc.reset_votes_for_participant(p_alice.id)
        p = svc._get_participant(p_alice.id)
        assert p.upvotes_count == 0
        assert p.downvotes_count == 0
        assert p.confirmed is False


# ===== Meta aggregation =====

class TestGetTournamentMeta:
    def test_meta_aggregates_by_archetype(self, svc, user_svc, tournament, user_alice, user_bob, archetype_burn, archetype_affinity):
        u3 = user_svc.get_or_create(tg_id=1003, username="carol")
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=user_bob.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=tournament.id, user_id=u3.id, archetype_id=archetype_affinity.id)

        meta = svc.get_tournament_meta(tournament.id)
        by_name = {row.archetype_name: row for row in meta}

        assert by_name["Burn"].count == 2
        assert by_name["Affinity"].count == 1

    def test_meta_empty_for_no_participants(self, svc, tournament):
        meta = svc.get_tournament_meta(tournament.id)
        assert meta == []


class TestListArchetypesForUser:
    def test_unknown_user_returns_top10_alphabetically(self, svc):
        for name in ("Burn", "Affinity", "Elves"):
            svc.get_or_create_archetype_by_name(name)
        result = svc.list_archetypes_for_user(tg_id=9999)
        names = [a.name for a in result]
        assert names == sorted(names)
        assert len(result) <= 10

    def test_recent_choice_comes_first(self, svc, tournament, user_alice, archetype_burn, archetype_affinity):
        svc.register_participant(tournament_id=tournament.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert result[0].name == "Burn"

    def test_most_recent_choice_wins(self, svc, db, user_alice, archetype_burn, archetype_affinity):
        from core.schemas import TournamentCreate
        import core.models as m
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=1))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=2))
        svc.register_participant(tournament_id=t1.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        # Make t2 participant appear newer
        p2 = m.Participant(
            tournament_id=t2.id, user_id=user_alice.id, archetype_id=archetype_affinity.id,
            added_by_admin=False, confirmed=False, upvotes_count=0, downvotes_count=0,
            created_at=utc_now() + timedelta(seconds=1),
            updated_at=utc_now(),
        )
        db.add(p2)
        db.commit()
        result = svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert result[0].name == "Affinity"
        assert result[1].name == "Burn"

    def test_deduplicates_repeated_choices(self, svc, db, user_alice, archetype_burn):
        from core.schemas import TournamentCreate
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=1))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=2))
        svc.register_participant(tournament_id=t1.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        svc.register_participant(tournament_id=t2.id, user_id=user_alice.id, archetype_id=archetype_burn.id)
        result = svc.list_archetypes_for_user(tg_id=user_alice.tg_id)
        assert [a.name for a in result].count("Burn") == 1

    def test_caps_at_total(self, svc):
        for i in range(15):
            svc.get_or_create_archetype_by_name(f"Arch{i:02d}")
        result = svc.list_archetypes_for_user(tg_id=9999, total=10)
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
        t = svc.create_tournament(TournamentCreate(title="A", chat_id=311, slug="a311"))
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


# ===== _get_participant error path =====

class TestGetParticipantNotFound:
    def test_raises_on_missing_participant(self, svc):
        from services.errors import ParticipantNotFound
        with pytest.raises(ParticipantNotFound):
            svc._get_participant(99999)


# ===== cast_vote edge cases =====

class TestCastVoteEdgeCases:
    @pytest.fixture
    def voting_setup(self, svc, user_svc):
        """Two chats each with their own tournament in VOTING state."""
        t1 = svc.create_tournament(TournamentCreate(title="T1", chat_id=400, slug="t1"))
        t2 = svc.create_tournament(TournamentCreate(title="T2", chat_id=401, slug="t2"))
        ua = user_svc.get_or_create(tg_id=4001, username="ua", first_name="UA")
        ub = user_svc.get_or_create(tg_id=4002, username="ub", first_name="UB")
        arch = svc.get_or_create_archetype_by_name("Burn")
        # Register participant before opening voting
        p = svc.register_participant(tournament_id=t1.id, user_id=ua.id, archetype_id=arch.id)
        svc.open_voting(t1.id)
        svc.open_voting(t2.id)
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
        from core import models as m
        from sqlalchemy import select
        part = svc.db.execute(select(m.Participant).where(m.Participant.id == p.id)).scalar_one()
        assert part.downvotes_count == 0
        assert part.upvotes_count == 1
