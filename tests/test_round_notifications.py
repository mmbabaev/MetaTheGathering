"""Tests for the new-round opponent notification feature (business logic only).

Covers:
- RoundNotificationService.build_for_round / build_for_rounds — recipient filtering,
  opponent lookup, deck history, byes, table numbers
- AetherhubImportService new-round detection + table_number persistence
- ArchetypeService.list_user_tournament_archetypes
- bot.messages.format_opponent_notification
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from bot.handlers.round_notify import RoundNotifyHandler
from bot.messages import format_opponent_notification
from bot.telegram.round_notify import send_debug_round_notifications, send_round_notifications
from core import models
from core.schemas import TournamentCreate
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.archetype import ArchetypeService
from services.datalens import DataLensService, StatRow
from services.round_notifications import RoundNotification, RoundNotificationService
from services.user import UserService


def _fake_datalens(opponent_decks, head_to_head):
    """DataLensService-заглушка: scout_opponent отдаёт заданные данные."""
    dl = MagicMock(spec=DataLensService)
    dl.scout_opponent.return_value = SimpleNamespace(opponent_decks=opponent_decks, head_to_head=head_to_head)
    return dl


# ── Helpers ──────────────────────────────────────────────────────────────────


def _tournament(svc, title="Current", chat_id=100, slug=None):
    return svc.create_tournament(TournamentCreate(title=title, chat_id=chat_id, slug=slug))


def _user(user_svc, tg_id, first_name, username=None):
    return user_svc.get_or_create(tg_id=tg_id, username=username, first_name=first_name)


def _participant(db, tournament_id, user_id, archetype_id=None, added_by_admin=False, created_at=None):
    p = models.Participant(
        tournament_id=tournament_id,
        user_id=user_id,
        archetype_id=archetype_id,
        added_by_admin=added_by_admin,
    )
    if created_at is not None:
        p.created_at = created_at
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _pairing(db, tournament_id, round_number, player_name, opponent_name, table_number=None):
    rp = models.RoundPairing(
        tournament_id=tournament_id,
        round_number=round_number,
        player_name=player_name,
        opponent_name=opponent_name,
        table_number=table_number,
    )
    db.add(rp)
    db.commit()
    return rp


def _make_data(players, rounds_pairings, standings=None):
    """rounds_pairings: list of rounds, each a list of (player, opponent, table_number)."""
    rounds = [
        AetherhubRound(
            number=i + 1,
            pairings=[AetherhubPairing(player=p, opponent=o, table_number=t) for p, o, t in pairs],
        )
        for i, pairs in enumerate(rounds_pairings)
    ]
    return AetherhubTournamentData(
        url="https://aetherhub.com/Tourney/RoundTourney/1",
        players=players,
        rounds=rounds,
        standings=standings or [],
    )


@pytest.fixture
def notif_svc(db):
    return RoundNotificationService(db)


# ── RoundNotificationService: happy path ───────────────────────────────────────


class TestBuildForRound:
    def test_self_registered_real_user_gets_full_notification(self, db, svc, user_svc, arch_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        opponent = _user(user_svc, 2002, "Opponent", username="opp")
        _participant(db, t.id, recipient.id, added_by_admin=False)
        _participant(db, t.id, opponent.id, added_by_admin=False)

        # opponent's past tournament deck (different tournament)
        past = _tournament(svc, title="Past", chat_id=200)
        burn = arch_svc.get_or_create_by_name("Burn")
        _participant(db, past.id, opponent.id, archetype_id=burn.id)

        # AetherHub stores both directions of a pairing
        _pairing(db, t.id, 1, "Recipient", "Opponent", table_number=7)
        _pairing(db, t.id, 1, "Opponent", "Recipient", table_number=7)

        notifs = notif_svc.build_for_round(t.id, 1)

        assert len(notifs) == 2  # both are self-registered real users paired with each other
        rec = next(n for n in notifs if n.tg_id == recipient.tg_id)
        assert rec.round_number == 1
        assert rec.table_number == 7
        assert rec.opponent_name == "Opponent"
        assert rec.opponent_username == "opp"
        assert rec.opponent_decks == ["Burn"]
        assert rec.is_bye is False

    def test_opponent_decks_exclude_current_tournament(self, db, svc, user_svc, arch_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        opponent = _user(user_svc, 2002, "Opponent")
        _participant(db, t.id, recipient.id)
        # opponent already has a deck in the CURRENT tournament — must be excluded
        affinity = arch_svc.get_or_create_by_name("Affinity")
        _participant(db, t.id, opponent.id, archetype_id=affinity.id)

        _pairing(db, t.id, 1, "Recipient", "Opponent")

        rec = notif_svc.build_for_round(t.id, 1)[0]
        assert rec.opponent_decks == []  # current-tournament deck excluded

    def test_opponent_decks_deduped_and_limited_to_three(self, db, svc, user_svc, arch_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        opponent = _user(user_svc, 2002, "Opponent")
        _participant(db, t.id, recipient.id)

        names = ["Burn", "Affinity", "Tron", "Elves"]
        archs = [arch_svc.get_or_create_by_name(n) for n in names]
        base = datetime(2026, 1, 1, 12, 0, 0)
        # 5 past tournaments; newest = Elves, then Tron, Affinity, Burn, Burn(dup)
        for i, arch in enumerate([archs[0], archs[0], archs[1], archs[2], archs[3]]):
            past = _tournament(svc, title=f"Past{i}", chat_id=300 + i)
            _participant(db, past.id, opponent.id, archetype_id=arch.id, created_at=base + timedelta(days=i))

        _pairing(db, t.id, 1, "Recipient", "Opponent")
        rec = notif_svc.build_for_round(t.id, 1)[0]
        # newest first, deduped, max 3
        assert rec.opponent_decks == ["Elves", "Tron", "Affinity"]

    def test_bye_produces_bye_notification(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        _participant(db, t.id, recipient.id)
        _pairing(db, t.id, 1, "Recipient", None, table_number=None)

        notifs = notif_svc.build_for_round(t.id, 1)
        assert len(notifs) == 1
        assert notifs[0].is_bye is True
        assert notifs[0].opponent_name is None
        assert notifs[0].opponent_decks == []

    def test_opponent_unknown_in_db(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        _participant(db, t.id, recipient.id)
        _pairing(db, t.id, 1, "Recipient", "Ghost Player", table_number=3)

        rec = notif_svc.build_for_round(t.id, 1)[0]
        assert rec.opponent_name == "Ghost Player"
        assert rec.opponent_username is None
        assert rec.opponent_decks == []

    def test_recipient_name_populated(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        recipient = user_svc.get_or_create(tg_id=2001, first_name="Иван", last_name="Иванов")
        _participant(db, t.id, recipient.id)
        _pairing(db, t.id, 1, "Иванов Иван", "Someone")

        rec = notif_svc.build_for_round(t.id, 1)[0]
        assert rec.recipient_name == "Иванов Иван"


class TestClosedTournamentSuppressesNotifications:
    """issue #114 — завершённый турнир не должен порождать уведомления ни на одном пути."""

    def _setup_pairing(self, db, svc, user_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        opponent = _user(user_svc, 2002, "Opponent", username="opp")
        _participant(db, t.id, recipient.id)
        _participant(db, t.id, opponent.id)
        _pairing(db, t.id, 1, "Recipient", "Opponent", table_number=7)
        _pairing(db, t.id, 1, "Opponent", "Recipient", table_number=7)
        return t

    def _set_status(self, db, t, status):
        tournament = db.get(models.Tournament, t.id)
        tournament.status = status
        db.commit()

    def test_closed_tournament_yields_no_notifications(self, db, svc, user_svc, notif_svc):
        t = self._setup_pairing(db, svc, user_svc)
        self._set_status(db, t, models.TournamentStatus.CLOSED)

        assert notif_svc.build_for_rounds(t.id, [1]) == []
        assert notif_svc.build_for_tournament(t.id) == []

    def test_ongoing_tournament_still_notifies(self, db, svc, user_svc, notif_svc):
        t = self._setup_pairing(db, svc, user_svc)
        self._set_status(db, t, models.TournamentStatus.ONGOING)

        assert len(notif_svc.build_for_rounds(t.id, [1])) == 2

    def test_voting_tournament_still_notifies(self, db, svc, user_svc, notif_svc):
        t = self._setup_pairing(db, svc, user_svc)
        self._set_status(db, t, models.TournamentStatus.VOTING)

        assert len(notif_svc.build_for_rounds(t.id, [1])) == 2


class TestDisplayName:
    def test_full_name(self, db, user_svc):
        u = user_svc.get_or_create(tg_id=1, first_name="Иван", last_name="Иванов")
        assert RoundNotificationService(db)._display_name(u) == "Иванов Иван"

    def test_username_fallback(self, db, user_svc):
        u = user_svc.get_or_create(tg_id=1, username="ivan")
        assert RoundNotificationService(db)._display_name(u) == "ivan"

    def test_id_fallback(self, db, user_svc):
        u = user_svc.get_or_create(tg_id=42)
        assert RoundNotificationService(db)._display_name(u) == "id42"


class TestDebugSenderOnlyMessagesRequester:
    """The debug button must DM the requester ONLY their own notifications — never broadcast."""

    async def test_sends_only_own_notifications_to_requester(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 2001, "Alice")
        bob = _user(user_svc, 2002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        # 2 rounds, both directions stored (as AetherHub does)
        for rnd in (1, 2):
            _pairing(db, t.id, rnd, "Alice", "Bob", table_number=rnd)
            _pairing(db, t.id, rnd, "Bob", "Alice", table_number=rnd)

        bot = AsyncMock()
        sent = await send_debug_round_notifications(bot, db, t.id, to_tg_id=alice.tg_id)

        # Alice has 2 rounds → exactly 2 messages, all to Alice, none about/for Bob's delivery
        assert sent == 2
        assert bot.send_message.await_count == 2
        for call in bot.send_message.await_args_list:
            assert call.kwargs["chat_id"] == alice.tg_id

    async def test_non_participant_requester_gets_nothing(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 2001, "Alice")
        bob = _user(user_svc, 2002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        _pairing(db, t.id, 1, "Alice", "Bob")
        _pairing(db, t.id, 1, "Bob", "Alice")

        admin_outsider = _user(user_svc, 9999, "Admin")
        bot = AsyncMock()
        sent = await send_debug_round_notifications(bot, db, t.id, to_tg_id=admin_outsider.tg_id)

        assert sent == 0
        bot.send_message.assert_not_awaited()

    async def test_debug_send_failure_is_swallowed(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 2001, "Alice")
        bob = _user(user_svc, 2002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        _pairing(db, t.id, 1, "Alice", "Bob")
        _pairing(db, t.id, 1, "Bob", "Alice")

        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("network down")
        sent = await send_debug_round_notifications(bot, db, t.id, to_tg_id=alice.tg_id)
        assert sent == 0  # error swallowed, no crash
        bot.send_message.assert_awaited()


def _opt_in(db, tg_id):
    obj = db.execute(select(models.User).where(models.User.tg_id == tg_id)).scalar_one()
    obj.notify_opponent_rounds = True
    db.commit()


class TestSendRoundNotificationsOptIn:
    """Per-user opt-in: only players with notify_opponent_rounds=True get notified."""

    def _setup(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 2001, "Alice")
        bob = _user(user_svc, 2002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        _pairing(db, t.id, 1, "Alice", "Bob")
        _pairing(db, t.id, 1, "Bob", "Alice")
        return t, alice, bob

    async def test_default_off_no_one_notified(self, db, svc, user_svc):
        t, _, _ = self._setup(db, svc, user_svc)
        bot = AsyncMock()
        sent = await send_round_notifications(bot, db, t.id, [1])
        assert sent == 0
        bot.send_message.assert_not_awaited()

    async def test_only_opted_in_user_notified(self, db, svc, user_svc):
        t, alice, bob = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        bot = AsyncMock()
        sent = await send_round_notifications(bot, db, t.id, [1])
        assert sent == 1
        targets = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
        assert targets == {alice.tg_id}  # bob did NOT opt in

    async def test_all_opted_in_everyone_notified(self, db, svc, user_svc):
        t, alice, bob = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        _opt_in(db, bob.tg_id)
        bot = AsyncMock()
        sent = await send_round_notifications(bot, db, t.id, [1])
        assert sent == 2
        targets = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
        assert targets == {alice.tg_id, bob.tg_id}

    async def test_no_rounds_sends_nothing(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        bot = AsyncMock()
        assert await send_round_notifications(bot, db, t.id, []) == 0
        bot.send_message.assert_not_awaited()

    async def test_none_bot_sends_nothing(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        assert await send_round_notifications(None, db, t.id, [1]) == 0

    async def test_allow_list_filters_recipient(self, db, svc, user_svc):
        t, alice, bob = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        _opt_in(db, bob.tg_id)
        # Debug allow-list excludes Bob → only Alice is delivered.
        with patch("bot.telegram.round_notify._is_notify_allowed", side_effect=lambda tg: tg == alice.tg_id):
            bot = AsyncMock()
            sent = await send_round_notifications(bot, db, t.id, [1])
        assert sent == 1
        targets = {c.kwargs["chat_id"] for c in bot.send_message.await_args_list}
        assert targets == {alice.tg_id}

    async def test_send_failure_is_swallowed(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("network down")
        sent = await send_round_notifications(bot, db, t.id, [1])
        assert sent == 0  # error swallowed, no crash
        bot.send_message.assert_awaited()


class TestGetRoundNumbers:
    def test_sorted_distinct(self, db, svc):
        t = _tournament(svc)
        _pairing(db, t.id, 2, "A", "B")
        _pairing(db, t.id, 1, "A", "B")
        _pairing(db, t.id, 1, "B", "A")
        _pairing(db, t.id, 3, "A", "B")
        assert AetherhubImportService(db).get_round_numbers(t.id) == [1, 2, 3]

    def test_empty(self, db, svc):
        t = _tournament(svc)
        assert AetherhubImportService(db).get_round_numbers(t.id) == []


# ── RoundNotificationService: recipient filtering ──────────────────────────────


class TestRecipientFiltering:
    def test_placeholder_recipient_negative_tg_id_skipped(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        # placeholder (added by hand) — negative tg_id
        placeholder, _ = user_svc.get_or_create_by_name("Placeholder", None)
        assert placeholder.tg_id < 0
        _participant(db, t.id, placeholder.id, added_by_admin=True)
        _pairing(db, t.id, 1, "Placeholder", "Someone")

        assert notif_svc.build_for_round(t.id, 1) == []

    def test_admin_added_participant_skipped(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        # real tg user, but added by an admin/scorekeeper — must NOT be notified
        real = _user(user_svc, 2001, "Real")
        _participant(db, t.id, real.id, added_by_admin=True)
        _pairing(db, t.id, 1, "Real", "Someone")

        assert notif_svc.build_for_round(t.id, 1) == []

    def test_player_not_a_participant_skipped(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        # user exists but never registered as a participant in this tournament
        _user(user_svc, 2001, "Lurker")
        _pairing(db, t.id, 1, "Lurker", "Someone")

        assert notif_svc.build_for_round(t.id, 1) == []

    def test_unknown_player_name_skipped(self, db, svc, notif_svc):
        t = _tournament(svc)
        _pairing(db, t.id, 1, "Nobody Known", "Someone")
        assert notif_svc.build_for_round(t.id, 1) == []

    def test_no_pairings_returns_empty(self, svc, notif_svc):
        t = _tournament(svc)
        assert notif_svc.build_for_round(t.id, 1) == []

    def test_only_requested_round_considered(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        _participant(db, t.id, recipient.id)
        _pairing(db, t.id, 1, "Recipient", "OppA")
        _pairing(db, t.id, 2, "Recipient", "OppB")

        notifs = notif_svc.build_for_round(t.id, 2)
        assert len(notifs) == 1
        assert notifs[0].opponent_name == "OppB"


# ── RoundNotificationService.build_for_rounds ──────────────────────────────────


class TestBuildForRounds:
    def test_flattens_multiple_rounds(self, db, svc, user_svc, notif_svc):
        t = _tournament(svc)
        recipient = _user(user_svc, 2001, "Recipient")
        _participant(db, t.id, recipient.id)
        _pairing(db, t.id, 1, "Recipient", "OppA")
        _pairing(db, t.id, 2, "Recipient", "OppB")

        notifs = notif_svc.build_for_rounds(t.id, [1, 2])
        assert {n.opponent_name for n in notifs} == {"OppA", "OppB"}

    def test_empty_round_list(self, svc, notif_svc):
        t = _tournament(svc)
        assert notif_svc.build_for_rounds(t.id, []) == []


# ── AetherhubImportService: new-round detection + table_number ─────────────────


class TestImportNewRoundDetection:
    def test_first_import_reports_all_rounds_new(self, db, svc):
        t = _tournament(svc)
        data = _make_data(
            players=["Alice", "Bob"],
            rounds_pairings=[
                [("Alice", "Bob", 1), ("Bob", "Alice", 1)],
                [("Alice", "Bob", 1), ("Bob", "Alice", 1)],
            ],
        )
        result = AetherhubImportService(db).import_tournament(t.id, data)
        assert result.new_round_numbers == [1, 2]

    def test_reimport_same_rounds_reports_none_new(self, db, svc):
        t = _tournament(svc)
        data = _make_data(["Alice", "Bob"], [[("Alice", "Bob", 1), ("Bob", "Alice", 1)]])
        svc_imp = AetherhubImportService(db)
        svc_imp.import_tournament(t.id, data)
        result = svc_imp.import_tournament(t.id, data)
        assert result.new_round_numbers == []

    def test_incremental_round_detected_as_new(self, db, svc):
        t = _tournament(svc)
        imp = AetherhubImportService(db)
        imp.import_tournament(t.id, _make_data(["Alice", "Bob"], [[("Alice", "Bob", 1), ("Bob", "Alice", 1)]]))
        # second import adds round 2
        data2 = _make_data(
            ["Alice", "Bob"],
            [
                [("Alice", "Bob", 1), ("Bob", "Alice", 1)],
                [("Alice", "Bob", 2), ("Bob", "Alice", 2)],
            ],
        )
        result = imp.import_tournament(t.id, data2)
        assert result.new_round_numbers == [2]

    def test_round_with_no_pairings_not_new(self, db, svc):
        t = _tournament(svc)
        data = AetherhubTournamentData(
            url="u",
            players=["Alice"],
            rounds=[AetherhubRound(number=1, pairings=[])],
            standings=[],
        )
        result = AetherhubImportService(db).import_tournament(t.id, data)
        assert result.new_round_numbers == []

    def test_table_number_persisted(self, db, svc):
        t = _tournament(svc)
        data = _make_data(["Alice", "Bob"], [[("Alice", "Bob", 12), ("Bob", "Alice", 12)]])
        imp = AetherhubImportService(db)
        imp.import_tournament(t.id, data)
        rows = imp.get_pairings(t.id, 1)
        assert all(r.table_number == 12 for r in rows)

    def test_table_number_updated_on_change(self, db, svc):
        t = _tournament(svc)
        imp = AetherhubImportService(db)
        imp.import_tournament(t.id, _make_data(["Alice", "Bob"], [[("Alice", "Bob", 1), ("Bob", "Alice", 1)]]))
        imp.import_tournament(t.id, _make_data(["Alice", "Bob"], [[("Alice", "Bob", 9), ("Bob", "Alice", 9)]]))
        rows = imp.get_pairings(t.id, 1)
        assert all(r.table_number == 9 for r in rows)


# ── ArchetypeService.list_user_tournament_archetypes ───────────────────────────


class TestUserTournamentArchetypes:
    def test_orders_newest_first_dedup_limit(self, db, svc, user_svc, arch_svc):
        user = _user(user_svc, 3001, "Player")
        names = ["Burn", "Affinity", "Tron", "Elves"]
        archs = {n: arch_svc.get_or_create_by_name(n) for n in names}
        base = datetime(2026, 1, 1)
        seq = ["Burn", "Burn", "Affinity", "Tron", "Elves"]
        for i, n in enumerate(seq):
            t = _tournament(svc, title=f"T{i}", chat_id=400 + i)
            _participant(db, t.id, user.id, archetype_id=archs[n].id, created_at=base + timedelta(days=i))

        result = arch_svc.list_user_tournament_archetypes(user.id, limit=3)
        assert [a.name for a in result] == ["Elves", "Tron", "Affinity"]

    def test_dedup_within_limit(self, db, svc, user_svc, arch_svc):
        # a repeated archetype before the limit is reached must be skipped, not counted twice
        user = _user(user_svc, 3001, "Player")
        burn = arch_svc.get_or_create_by_name("Burn")
        tron = arch_svc.get_or_create_by_name("Tron")
        base = datetime(2026, 1, 1)
        # newest-first: Burn, Burn, Tron
        for i, arch in enumerate([tron, burn, burn]):
            t = _tournament(svc, title=f"D{i}", chat_id=700 + i)
            _participant(db, t.id, user.id, archetype_id=arch.id, created_at=base + timedelta(days=i))

        result = arch_svc.list_user_tournament_archetypes(user.id, limit=3)
        assert [a.name for a in result] == ["Burn", "Tron"]

    def test_excludes_given_tournament(self, db, svc, user_svc, arch_svc):
        user = _user(user_svc, 3001, "Player")
        burn = arch_svc.get_or_create_by_name("Burn")
        current = _tournament(svc, chat_id=500)
        _participant(db, current.id, user.id, archetype_id=burn.id)

        result = arch_svc.list_user_tournament_archetypes(user.id, exclude_tournament_id=current.id)
        assert result == []

    def test_ignores_participants_without_archetype(self, db, svc, user_svc, arch_svc):
        user = _user(user_svc, 3001, "Player")
        t = _tournament(svc, chat_id=600)
        _participant(db, t.id, user.id, archetype_id=None)
        assert arch_svc.list_user_tournament_archetypes(user.id) == []

    def test_no_user_no_decks(self, arch_svc):
        assert arch_svc.list_user_tournament_archetypes(999999) == []


# ── bot.messages.format_opponent_notification ──────────────────────────────────


class TestFormatNotification:
    def test_full_message(self):
        text = format_opponent_notification(2, 5, "Иванов Иван", "ivan", ["Burn", "Affinity"])
        assert "Раунд 2" in text
        assert "Стол №5" in text
        assert "Иванов Иван (@ivan)" in text
        assert "• Burn" in text
        assert "• Affinity" in text

    def test_no_table_number_omits_table_line(self):
        text = format_opponent_notification(1, None, "Bob", None, ["Tron"])
        assert "Стол" not in text
        assert "Оппонент:" in text
        assert "Bob" in text

    def test_no_username(self):
        text = format_opponent_notification(1, 1, "Bob", None, ["Tron"])
        assert "@" not in text

    def test_no_decks_shows_placeholder(self):
        text = format_opponent_notification(1, 1, "Bob", None, [])
        assert "не найдены" in text

    def test_bye_message(self):
        text = format_opponent_notification(3, None, None, None, is_bye=True)
        assert "бай" in text.lower()
        assert "Оппонент" not in text

    def test_datalens_decks_override_db_decks_with_winrate(self):
        decks = [StatRow(name="Flicker Tron", matches=49, winrate=67.3)]
        text = format_opponent_notification(1, 3, "Вадим", None, ["OldDeck"], datalens_decks=decks)
        assert "Flicker Tron" in text
        assert "67%" in text
        assert "(49 матчей)" in text
        assert "OldDeck" not in text  # DataLens заменяет список из БД бота
        assert "3 мес" in text

    def test_head_to_head_line(self):
        h2h = StatRow(name="Вадим", matches=8, winrate=33.3)
        text = format_opponent_notification(1, 3, "Вадим", None, [], head_to_head=h2h)
        assert "Матчей против оппонента: 8" in text
        assert "33%" in text

    def test_no_datalens_falls_back_to_db_decks(self):
        text = format_opponent_notification(1, 3, "Вадим", None, ["Tron"])
        assert "• Tron" in text
        assert "Последние колоды" in text


# ── RoundNotificationService.scout (DataLens enrichment) ───────────────────────


class TestScout:
    def test_returns_decks_and_head_to_head(self, db):
        decks = [StatRow(name="Flicker Tron", matches=49, winrate=67.3)]
        h2h = StatRow(name="Ашаров Вадим", matches=8, winrate=33.3)
        svc = RoundNotificationService(db, datalens_service=_fake_datalens(decks, h2h))
        got_decks, got_h2h = svc.scout("Бабаев Михаил", "Ашаров Вадим")
        assert got_decks == decks
        assert got_h2h == h2h

    def test_limits_decks_to_three(self, db):
        decks = [StatRow(name=f"D{i}", matches=10 - i, winrate=50.0) for i in range(5)]
        svc = RoundNotificationService(db, datalens_service=_fake_datalens(decks, None))
        got_decks, _ = svc.scout("P", "O")
        assert len(got_decks) == 3

    def test_no_datalens_returns_empty(self, db):
        svc = RoundNotificationService(db)  # datalens not injected
        assert svc.scout("P", "O") == ([], None)

    def test_bye_opponent_none_returns_empty_without_calling_api(self, db):
        dl = _fake_datalens([StatRow(name="x", matches=1, winrate=1)], None)
        svc = RoundNotificationService(db, datalens_service=dl)
        assert svc.scout("P", None) == ([], None)
        dl.scout_opponent.assert_not_called()

    def test_exception_is_swallowed(self, db):
        dl = MagicMock(spec=DataLensService)
        dl.scout_opponent.side_effect = RuntimeError("network down")
        svc = RoundNotificationService(db, datalens_service=dl)
        assert svc.scout("P", "O") == ([], None)


# ── RoundNotifyHandler (pure logic) ────────────────────────────────────────────


class TestRoundNotifyHandler:
    def _handler(self, db, datalens=None):
        return RoundNotifyHandler(RoundNotificationService(db, datalens_service=datalens), UserService(db))

    def _setup(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 3001, "Alice")
        bob = _user(user_svc, 3002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        _pairing(db, t.id, 1, "Alice", "Bob")
        _pairing(db, t.id, 1, "Bob", "Alice")
        return t, alice, bob

    def test_only_opted_in_recipients(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        messages = self._handler(db).build_for_new_rounds(t.id, [1])
        assert [m.tg_id for m in messages] == [alice.tg_id]

    def test_allow_list_predicate_applied(self, db, svc, user_svc):
        t, alice, bob = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        _opt_in(db, bob.tg_id)
        messages = self._handler(db).build_for_new_rounds(t.id, [1], is_allowed=lambda tg: tg == alice.tg_id)
        assert [m.tg_id for m in messages] == [alice.tg_id]

    def test_message_enriched_with_datalens(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        dl = _fake_datalens(
            [StatRow(name="Flicker Tron", matches=49, winrate=67.3)],
            StatRow(name="Bob", matches=8, winrate=33.3),
        )
        messages = self._handler(db, dl).build_for_new_rounds(t.id, [1])
        assert "Flicker Tron" in messages[0].text
        assert "67%" in messages[0].text
        assert "Матчей против оппонента: 8" in messages[0].text

    def test_datalens_not_queried_for_non_opted_in(self, db, svc, user_svc):
        t, _, _ = self._setup(db, svc, user_svc)  # nobody opts in
        dl = MagicMock(spec=DataLensService)
        messages = self._handler(db, dl).build_for_new_rounds(t.id, [1])
        assert messages == []
        dl.scout_opponent.assert_not_called()

    def test_build_for_requester_only_own(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        # opt-in is irrelevant for the debug/requester path
        messages = self._handler(db).build_for_requester(t.id, alice.tg_id)
        assert messages and all(m.tg_id == alice.tg_id for m in messages)

    def test_debug_and_prod_render_identical_text(self, db, svc, user_svc):
        # the core guarantee: debug preview == production message (same data, same
        # enrichment, same formatting) — only recipient selection/delivery differ.
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        dl = _fake_datalens(
            [StatRow(name="Flicker Tron", matches=49, winrate=67.3)],
            StatRow(name="Bob", matches=8, winrate=33.3),
        )
        handler = self._handler(db, dl)
        prod_text = next(m.text for m in handler.build_for_new_rounds(t.id, [1]) if m.tg_id == alice.tg_id)
        debug_text = next(m.text for m in handler.build_for_requester(t.id, alice.tg_id) if m.tg_id == alice.tg_id)
        assert prod_text == debug_text
        assert "Flicker Tron" in prod_text  # both went through DataLens enrichment


class TestEnrich:
    def test_enrich_populates_datalens_fields(self, db):
        decks = [StatRow(name="Elves", matches=24, winrate=60.0)]
        h2h = StatRow(name="Иванов", matches=3, winrate=22.0)
        svc = RoundNotificationService(db, datalens_service=_fake_datalens(decks, h2h))
        n = RoundNotification(
            tg_id=1,
            round_number=4,
            table_number=7,
            opponent_name="Иванов",
            opponent_username=None,
            recipient_name="Бабаев Михаил",
        )
        out = svc.enrich(n)
        assert out is n  # in-place
        assert n.datalens_decks == decks
        assert n.head_to_head == h2h

    def test_enrich_no_datalens_leaves_empty(self, db):
        svc = RoundNotificationService(db)  # no DataLens injected
        n = RoundNotification(
            tg_id=1,
            round_number=1,
            table_number=1,
            opponent_name="X",
            opponent_username=None,
            recipient_name="Me",
        )
        svc.enrich(n)
        assert n.datalens_decks == [] and n.head_to_head is None


# ── send_round_notifications: DataLens enrichment end-to-end ────────────────────


class TestSendRoundNotificationsDataLens:
    def _setup(self, db, svc, user_svc):
        t = _tournament(svc)
        alice = _user(user_svc, 4001, "Alice")
        bob = _user(user_svc, 4002, "Bob")
        _participant(db, t.id, alice.id)
        _participant(db, t.id, bob.id)
        _pairing(db, t.id, 1, "Alice", "Bob")
        _pairing(db, t.id, 1, "Bob", "Alice")
        return t, alice, bob

    async def test_message_enriched(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        dl = _fake_datalens(
            [StatRow(name="Flicker Tron", matches=49, winrate=67.3)],
            StatRow(name="Bob", matches=8, winrate=33.3),
        )
        bot = AsyncMock()
        sent = await send_round_notifications(bot, db, t.id, [1], datalens_service=dl)
        assert sent == 1
        text = bot.send_message.await_args.kwargs["text"]
        assert "Flicker Tron" in text
        assert "Матчей против оппонента: 8" in text

    async def test_without_datalens_still_sends_base_message(self, db, svc, user_svc):
        t, alice, _ = self._setup(db, svc, user_svc)
        _opt_in(db, alice.tg_id)
        bot = AsyncMock()
        sent = await send_round_notifications(bot, db, t.id, [1])  # no datalens_service
        assert sent == 1
        assert "Раунд 1" in bot.send_message.await_args.kwargs["text"]
