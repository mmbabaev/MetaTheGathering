"""Tests for the per-user 'status by pairings' setting (#88).

The setting lays out the admin participant KEYBOARD by table — two player buttons
per row (one row = one pairing) — instead of a single column. The status text stays
flat. Covered: pairings→participants resolver, keyboard layout, the toggle.
"""

from types import SimpleNamespace

from bot.handlers.settings import SettingsHandler
from bot.handlers.tournament_status import pairing_rows
from bot.keyboards import admin_participants_keyboard
from core import models
from core.schemas import TournamentCreate


def _participant(last, first, archetype=None, pid=1, uid=1):
    user = SimpleNamespace(first_name=first, last_name=last, username=None, tg_id=uid, is_scorekeeper=False)
    arch = SimpleNamespace(name=archetype) if archetype else None
    return SimpleNamespace(user=user, archetype=arch, user_id=uid, id=pid)


# ── keyboard layout by pairings ────────────────────────────────────────────────


class TestKeyboardByPairings:
    def test_two_buttons_per_table_row(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", "Burn", pid=2, uid=2)
        c = _participant("Сидоров", "Сидор", None, pid=3, uid=3)
        d = _participant("Кузнецов", "Кузьма", "Elves", pid=4, uid=4)
        pairs = [(1, a, "A", b, "B"), (2, c, "C", d, "D")]
        kb = admin_participants_keyboard([a, b, c, d], tournament_id=10, pairs=pairs, unpaired=[])
        rows = kb.inline_keyboard
        assert len(rows[0]) == 2 and len(rows[1]) == 2  # one row per table, two buttons
        assert rows[0][0].text.endswith("Иванов Иван") and rows[0][0].callback_data == "adm_pick:1"
        assert rows[-1][0].text == "⬅️ Назад"

    def test_bye_row_has_single_button(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        kb = admin_participants_keyboard([a], tournament_id=10, pairs=[(1, a, "A", None, None)], unpaired=[])
        assert len(kb.inline_keyboard[0]) == 1  # bye → lone button

    def test_unresolved_opponent_dropped(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        # opponent name present but not a registered participant (p2 is None)
        kb = admin_participants_keyboard([a], tournament_id=10, pairs=[(1, a, "A", None, "Гость")], unpaired=[])
        assert len(kb.inline_keyboard[0]) == 1

    def test_unpaired_appended_two_per_row(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        u1 = _participant("Новый", "Ник", None, pid=8, uid=8)
        u2 = _participant("Гость", "Гена", None, pid=9, uid=9)
        kb = admin_participants_keyboard(
            [a, u1, u2], tournament_id=10, pairs=[(1, a, "A", None, None)], unpaired=[u1, u2]
        )
        rows = kb.inline_keyboard
        assert len(rows[0]) == 1  # bye
        assert len(rows[1]) == 2  # the two unpaired, side by side

    def test_flat_layout_when_no_pairs(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", None, pid=2, uid=2)
        kb = admin_participants_keyboard([a, b], tournament_id=10)  # pairs=None → current flat column
        # every non-back row holds exactly one button
        assert all(len(r) == 1 for r in kb.inline_keyboard)


# ── DB resolver ────────────────────────────────────────────────────────────────


def _two_player_tournament(db, svc, user_svc, arch_svc, *, with_pairings: bool):
    t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
    alice = user_svc.get_or_create(tg_id=1, first_name="Иван", last_name="Иванов")
    bob = user_svc.get_or_create(tg_id=2, first_name="Пётр", last_name="Петров")
    burn = arch_svc.get_or_create_by_name("Burn")
    svc.register_participant(tournament_id=t.id, user_id=alice.id, archetype_id=burn.id)
    svc.register_participant(tournament_id=t.id, user_id=bob.id)  # no deck
    if with_pairings:
        for p1, p2 in [("Иванов Иван", "Петров Пётр"), ("Петров Пётр", "Иванов Иван")]:
            db.add(
                models.RoundPairing(
                    tournament_id=t.id, round_number=1, player_name=p1, opponent_name=p2, table_number=1
                )
            )
        db.commit()
    return t.id


def test_pairing_rows_resolves_participants(db, svc, user_svc, arch_svc):
    tid = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=True)
    participants = svc.list_participants_for_tournament(tid)
    pairs, unpaired = pairing_rows(db, tid, participants)
    assert len(pairs) == 1  # both directions collapsed into one table
    _table, p1, n1, p2, n2 = pairs[0]
    assert {n1, n2} == {"Иванов Иван", "Петров Пётр"}
    assert p1 is not None and p2 is not None
    assert unpaired == []


def test_pairing_rows_none_without_pairings(db, svc, user_svc, arch_svc):
    tid = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=False)
    assert pairing_rows(db, tid, svc.list_participants_for_tournament(tid)) is None


def _name(i):
    return f"Фам{i} Имя{i}"


def _tournament_with_scrambled_tables(db, svc, user_svc, rows):
    """Create a tournament + participants for P1.. and insert ``rows`` of
    ``(table, player_name, opponent_name)`` in the given (scrambled) DB order."""
    t = svc.create_tournament(TournamentCreate(title="T", chat_id=1))
    players = {n for _, p, o in rows for n in (p, o) if n}
    for n in players:
        i = int(n.split()[0].removeprefix("Фам"))
        u = user_svc.get_or_create(tg_id=i, first_name=f"Имя{i}", last_name=f"Фам{i}")
        svc.register_participant(tournament_id=t.id, user_id=u.id)
    for tbl, p, o in rows:
        db.add(
            models.RoundPairing(tournament_id=t.id, round_number=1, player_name=p, opponent_name=o, table_number=tbl)
        )
    db.commit()
    return t.id


def test_pairing_rows_ordered_by_table_number(db, svc, user_svc):
    # insert tables OUT OF ORDER (3, 1, 2) — resolver must return them 1, 2, 3
    rows = [
        (3, _name(5), _name(6)),
        (3, _name(6), _name(5)),
        (1, _name(1), _name(2)),
        (1, _name(2), _name(1)),
        (2, _name(3), _name(4)),
        (2, _name(4), _name(3)),
    ]
    tid = _tournament_with_scrambled_tables(db, svc, user_svc, rows)
    pairs, unpaired = pairing_rows(db, tid, svc.list_participants_for_tournament(tid))
    assert [tbl for tbl, *_ in pairs] == [1, 2, 3]  # by table number, not DB insert order
    assert unpaired == []
    # each pairing keeps both registered players
    assert all(p1 is not None and p2 is not None for _, p1, _, p2, _ in pairs)


def test_pairing_rows_table_order_with_bye(db, svc, user_svc):
    # odd player count: table 3 is a bye (opponent None); tables inserted scrambled
    rows = [
        (2, _name(3), _name(4)),
        (2, _name(4), _name(3)),
        (3, _name(5), None),  # bye
        (1, _name(1), _name(2)),
        (1, _name(2), _name(1)),
    ]
    tid = _tournament_with_scrambled_tables(db, svc, user_svc, rows)
    pairs, _unpaired = pairing_rows(db, tid, svc.list_participants_for_tournament(tid))
    assert [tbl for tbl, *_ in pairs] == [1, 2, 3]
    assert pairs[-1][4] is None  # table 3: bye → opponent name is None


# ── setting toggle ─────────────────────────────────────────────────────────────


def test_user_service_toggle(db, user_svc):
    user_svc.get_or_create(tg_id=5, first_name="X")
    assert user_svc.wants_status_by_pairings(5) is False
    assert user_svc.toggle_status_by_pairings(5) is True
    assert user_svc.wants_status_by_pairings(5) is True
    assert user_svc.toggle_status_by_pairings(5) is False


def test_settings_handler_toggle(db, user_svc):
    user_svc.get_or_create(tg_id=5, first_name="X")
    SettingsHandler(user_svc).handle_toggle_status_by_pairings(5)
    assert user_svc.wants_status_by_pairings(5) is True
