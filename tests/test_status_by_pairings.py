"""Tests for the per-user 'tournament status grouped by pairings' setting (#88)."""

from types import SimpleNamespace

from bot.handlers.settings import SettingsHandler
from bot.handlers.tournament_status import _pairing_rows, status_text
from bot.messages import format_tournament_status_by_pairings
from core import models
from core.schemas import TournamentCreate

# ── pure formatter ─────────────────────────────────────────────────────────────


def _participant(last, first, archetype=None, uid=1, username=None):
    user = SimpleNamespace(first_name=first, last_name=last, username=username, tg_id=uid, is_scorekeeper=False)
    arch = SimpleNamespace(name=archetype) if archetype else None
    return SimpleNamespace(user=user, archetype=arch, user_id=uid)


class TestFormatter:
    def test_pairs_bye_and_unpaired(self):
        a = _participant("Иванов", "Иван", "Burn", 1)
        b = _participant("Петров", "Пётр", None, 2)
        c = _participant("Сидоров", "Сидор", "Affinity", 3)
        u = _participant("Новый", "Ник", None, 9)
        pairs = [(1, a, "Иванов Иван", b, "Петров Пётр"), (2, c, "Сидоров Сидор", None, None)]
        text = format_tournament_status_by_pairings("T", "Регистрация", [a, b, c, u], pairs, [u])
        assert "🏆 T · Регистрация · 4 чел." in text
        assert "✅ 2 с колодой  ⬜ 2 без" in text  # a, c filled; b, u empty
        assert "— Стол 1 —" in text
        assert "✅ Иванов Иван — Burn" in text
        assert "⬜ Петров Пётр — не указана" in text
        assert "BYE" in text  # Сидоров's bye
        assert "Без пары:" in text and "Новый Ник" in text

    def test_unregistered_opponent_name(self):
        a = _participant("Иванов", "Иван", "Burn", 1)
        pairs = [(1, a, "Иванов Иван", None, "Гость Гостев")]  # name set, no participant
        text = format_tournament_status_by_pairings("T", "Рег", [a], pairs, [])
        assert "❓ Гость Гостев — не участвует" in text


# ── DB: resolver + status_text branching ───────────────────────────────────────


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
    return db.get(models.Tournament, t.id)


def test_pairing_rows_resolves_participants(db, svc, user_svc, arch_svc):
    t = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=True)
    participants = svc.list_participants_for_tournament(t.id)
    pairs, unpaired = _pairing_rows(db, t.id, participants)
    assert len(pairs) == 1  # both directions collapsed
    table, p1, n1, p2, n2 = pairs[0]
    assert {n1, n2} == {"Иванов Иван", "Петров Пётр"}
    assert p1 is not None and p2 is not None  # both resolved to participants
    assert unpaired == []


def test_pairing_rows_none_without_pairings(db, svc, user_svc, arch_svc):
    t = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=False)
    assert _pairing_rows(db, t.id, svc.list_participants_for_tournament(t.id)) is None


def test_status_text_by_pairings(db, svc, user_svc, arch_svc):
    t = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=True)
    parts = svc.list_participants_for_tournament(t.id)
    text = status_text(db, t, parts, by_pairings=True, decks_hidden=False)
    assert "— Стол 1 —" in text
    assert "Иванов Иван" in text and "Петров Пётр" in text


def test_status_text_flat_when_setting_off(db, svc, user_svc, arch_svc):
    t = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=True)
    parts = svc.list_participants_for_tournament(t.id)
    text = status_text(db, t, parts, by_pairings=False, decks_hidden=False)
    assert "Стол" not in text  # flat list, current behavior unchanged


def test_status_text_falls_back_to_flat_without_pairings(db, svc, user_svc, arch_svc):
    t = _two_player_tournament(db, svc, user_svc, arch_svc, with_pairings=False)
    parts = svc.list_participants_for_tournament(t.id)
    text = status_text(db, t, parts, by_pairings=True, decks_hidden=False)
    assert "Стол" not in text  # no pairings → flat fallback


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
