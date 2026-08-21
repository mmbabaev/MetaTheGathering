"""Tests for the per-user 'status by pairings' setting (#88).

The setting lays out the admin participant KEYBOARD by table — two player buttons
per row (one row = one pairing) — instead of a single column. The status text stays
flat. Covered: pairings→participants resolver, keyboard layout, the toggle.
"""

from types import SimpleNamespace

from bot.handlers.settings import SettingsHandler
from bot.handlers.tournament_status import pairing_rows
from bot.keyboards import StatusButton, admin_participants_keyboard, participant_button_rows
from core import models
from core.schemas import TournamentCreate


def _participant(last, first, archetype=None, pid=1, uid=1):
    user = SimpleNamespace(first_name=first, last_name=last, username=None, tg_id=uid, is_scorekeeper=False)
    arch = SimpleNamespace(name=archetype) if archetype else None
    return SimpleNamespace(user=user, archetype=arch, user_id=uid, id=pid)


# ── pure button model: FLAT mode (feature OFF) — must keep old behaviour ────────


class TestFlatButtonModel:
    def test_shows_only_unfilled_one_per_row(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", "Burn", pid=2, uid=2)  # filled → hidden by default
        rows = participant_button_rows([a, b], tournament_id=10)
        assert rows[0] == [StatusButton("📝 Иванов Иван", "adm_pick:1")]
        assert rows[1][0].label == "Показать заполненных (1)"
        assert rows[-1] == [StatusButton("⬅️ Назад", "t:10")]
        assert all(len(r) == 1 for r in rows)  # plain column, one button per row

    def test_show_filled_includes_filled_and_no_toggle(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", "Burn", pid=2, uid=2)
        rows = participant_button_rows([a, b], tournament_id=10, show_filled=True)
        labels = [btn.label for row in rows for btn in row]
        assert "📝 Иванов Иван" in labels and "✏️ Петров Пётр" in labels
        assert not any("Показать заполненных" in x for x in labels)

    def test_preserves_input_order(self):
        # the handler pre-sorts participants; the model must keep that exact order
        a = _participant("Яковлев", "Яков", None, pid=1, uid=1)
        b = _participant("Аакёров", "Аак", None, pid=2, uid=2)
        rows = participant_button_rows([a, b], tournament_id=10)
        assert rows[0][0].callback_data == "adm_pick:1" and rows[1][0].callback_data == "adm_pick:2"


# ── pure button model: BY-PAIRINGS mode (feature ON) — order by table ───────────


class TestPairingButtonModel:
    def test_one_row_per_table_with_number_prefixed_on_first(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", "Burn", pid=2, uid=2)
        c = _participant("Сидоров", "Сидор", None, pid=3, uid=3)
        d = _participant("Кузнецов", "Кузьма", "Elves", pid=4, uid=4)
        pairs = [(1, a, "A", b, "B"), (2, c, "C", d, "D")]  # resolver gives table order
        rows = participant_button_rows([a, b, c, d], tournament_id=10, pairs=pairs, unpaired=[])
        # один ряд на стол; номер стола — префиксом на первой кнопке
        assert [b.callback_data for b in rows[0]] == ["adm_pick:1", "adm_pick:2"]
        assert rows[0][0].label.startswith("№1 · ")
        assert [b.callback_data for b in rows[1]] == ["adm_pick:3", "adm_pick:4"]
        assert rows[1][0].label.startswith("№2 · ")
        assert rows[-1] == [StatusButton("⬅️ Назад", "t:10")]

    def test_second_player_has_no_table_prefix(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", None, pid=2, uid=2)
        rows = participant_button_rows([a, b], tournament_id=10, pairs=[(7, a, "A", b, "B")], unpaired=[])
        assert rows[0][0].label.startswith("№7 · ")
        assert not rows[0][1].label.startswith("№")  # у второго игрока номера нет

    def test_no_prefix_when_table_unknown(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", None, pid=2, uid=2)
        rows = participant_button_rows([a, b], tournament_id=10, pairs=[(None, a, "A", b, "B")], unpaired=[])
        assert [b.callback_data for b in rows[0]] == ["adm_pick:1", "adm_pick:2"]
        assert not rows[0][0].label.startswith("№")  # номер стола неизвестен → без префикса

    def test_row_order_follows_pairs(self):
        parts = [_participant(f"Ф{i}", f"И{i}", None, pid=i, uid=i) for i in range(1, 5)]
        a, b, c, d = parts
        pairs = [(5, a, "A", b, "B"), (6, c, "C", d, "D")]  # already table-ordered by resolver
        rows = participant_button_rows(parts, tournament_id=10, pairs=pairs, unpaired=[])
        assert [r[0].callback_data for r in rows] == ["adm_pick:1", "adm_pick:3", "t:10"]
        assert [rows[0][0].label.startswith("№5 · "), rows[1][0].label.startswith("№6 · ")] == [True, True]

    def test_bye_is_single_player_with_prefix(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        rows = participant_button_rows([a], tournament_id=10, pairs=[(1, a, "A", None, None)], unpaired=[])
        assert [b.callback_data for b in rows[0]] == ["adm_pick:1"]
        assert rows[0][0].label.startswith("№1 · ")

    def test_unresolved_opponent_is_single_player_with_prefix(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        rows = participant_button_rows([a], tournament_id=10, pairs=[(1, a, "A", None, "Гость")], unpaired=[])
        assert [b.callback_data for b in rows[0]] == ["adm_pick:1"]  # оппонент не участник → без кнопки
        assert rows[0][0].label.startswith("№1 · ")

    def test_unpaired_two_per_row_without_prefix(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        u1 = _participant("Новый", "Ник", None, pid=8, uid=8)
        u2 = _participant("Гость", "Гена", None, pid=9, uid=9)
        rows = participant_button_rows(
            [a, u1, u2], tournament_id=10, pairs=[(1, a, "A", None, None)], unpaired=[u1, u2]
        )
        assert rows[0][0].label.startswith("№1 · ")  # bye — один игрок с префиксом стола
        assert [b.callback_data for b in rows[1]] == ["adm_pick:8", "adm_pick:9"]  # unpaired — без префикса
        assert not rows[1][0].label.startswith("№")

    def test_filled_table_hidden_by_default_with_show_all_button(self):
        a = _participant("Иванов", "Иван", "Burn", pid=1, uid=1)  # с колодой
        b = _participant("Петров", "Пётр", "Elves", pid=2, uid=2)  # с колодой → стол 1 заполнен
        c = _participant("Сидоров", "Сидор", None, pid=3, uid=3)  # без колоды → стол 2 нет
        d = _participant("Кузнецов", "Кузьма", None, pid=4, uid=4)
        pairs = [(1, a, "A", b, "B"), (2, c, "C", d, "D")]
        rows = participant_button_rows([a, b, c, d], tournament_id=10, pairs=pairs, unpaired=[])
        # заполненный стол 1 скрыт; показан только стол 2 + «показать все» + назад
        assert [b.callback_data for b in rows[0]] == ["adm_pick:3", "adm_pick:4"]
        assert rows[0][0].label.startswith("№2 · ")
        assert rows[1] == [StatusButton("Показать все столы (1)", "adm_show_filled:10")]
        assert rows[-1] == [StatusButton("⬅️ Назад", "t:10")]

    def test_show_filled_reveals_all_tables(self):
        a = _participant("Иванов", "Иван", "Burn", pid=1, uid=1)
        b = _participant("Петров", "Пётр", "Elves", pid=2, uid=2)
        rows = participant_button_rows(
            [a, b], tournament_id=10, pairs=[(1, a, "A", b, "B")], unpaired=[], show_filled=True
        )
        assert [b.callback_data for b in rows[0]] == ["adm_pick:1", "adm_pick:2"]
        assert rows[0][0].label.startswith("№1 · ")
        assert all("Показать все столы" not in r[0].label for r in rows)  # уже показываем всё

    def test_partially_filled_table_still_shown(self):
        a = _participant("Иванов", "Иван", "Burn", pid=1, uid=1)  # с колодой
        b = _participant("Петров", "Пётр", None, pid=2, uid=2)  # без колоды → стол не заполнен
        rows = participant_button_rows([a, b], tournament_id=10, pairs=[(1, a, "A", b, "B")], unpaired=[])
        assert rows[0][0].label.startswith("№1 · ")  # показан
        assert not any("Показать все столы" in r[0].label for r in rows)

    def test_bye_table_with_deck_is_hidden(self):
        a = _participant("Иванов", "Иван", "Burn", pid=1, uid=1)  # бай, с колодой → стол заполнен
        rows = participant_button_rows([a], tournament_id=10, pairs=[(1, a, "A", None, None)], unpaired=[])
        assert rows[0] == [StatusButton("Показать все столы (1)", "adm_show_filled:10")]
        assert rows[-1] == [StatusButton("⬅️ Назад", "t:10")]


# ── thin Telegram adapter faithfully mirrors the model ─────────────────────────


class TestKeyboardAdapter:
    def test_markup_mirrors_model(self):
        a = _participant("Иванов", "Иван", None, pid=1, uid=1)
        b = _participant("Петров", "Пётр", None, pid=2, uid=2)
        pairs = [(1, a, "A", b, "B")]
        model = participant_button_rows([a, b], tournament_id=10, pairs=pairs, unpaired=[])
        kb = admin_participants_keyboard([a, b], tournament_id=10, pairs=pairs, unpaired=[])
        assert [[btn.text for btn in row] for row in kb.inline_keyboard] == [[b.label for b in r] for r in model]
        assert kb.inline_keyboard[0][0].callback_data == model[0][0].callback_data


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
