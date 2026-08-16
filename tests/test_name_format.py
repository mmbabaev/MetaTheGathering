"""Tests for name formatting heuristic and participant sort order."""

import pytest

from bot.messages import family_name_sort_key, format_participant_name
from bot.messages import sort_participants as _sort_participants
from core import models
from core.schemas import TournamentCreate
from services.names import is_single_word_name_typo


class TestSingleWordNameTypo:
    def test_accepts_issue_233_missing_letter_in_either_order(self):
        assert is_single_word_name_typo("Бурбаев Констанин", "Константин Бурбаев") is True

    @pytest.mark.parametrize(
        ("imported", "candidate"),
        [
            ("Бурбаев Константин", "Константин Бурбаев"),  # exact, not a typo
            ("Иван Иван", "Иван Иван"),  # repeated words must stay safe
            ("Иванов Илья", "Иванов Игорь"),  # more than one edit
            ("Ли Ан", "Ли Ян"),  # short names are too risky for fuzzy matching
        ],
    )
    def test_rejects_unsafe_or_non_typo_pairs(self, imported, candidate):
        assert is_single_word_name_typo(imported, candidate) is False


class TestFormatParticipantName:
    # split fields (last_name set) — always "last first"
    def test_split_last_before_first(self):
        assert format_participant_name("Антон", "Ильин") == "Ильин Антон"

    def test_split_last_name_only(self):
        assert format_participant_name(None, "Ильин") == "Ильин"

    def test_split_first_name_only(self):
        assert format_participant_name("Антон", None) == "Антон"

    def test_both_none(self):
        assert format_participant_name(None, None) == ""

    # single-field "Имя Фамилия" — last word looks like family name → reverse
    def test_single_field_ima_familiya_reversed(self):
        assert format_participant_name("Дмитрий Оленин", None) == "Оленин Дмитрий"

    def test_single_field_karpovskyy(self):
        assert format_participant_name("Евгений Карповский", None) == "Карповский Евгений"

    def test_single_field_ov_suffix(self):
        assert format_participant_name("Иван Иванов", None) == "Иванов Иван"

    # single-field "Фамилия Имя" — last word NOT a family suffix → keep as-is
    def test_single_field_familiya_ima_kept(self):
        assert format_participant_name("Кузнецов Ярослав", None) == "Кузнецов Ярослав"

    def test_single_field_pupkin_vasya(self):
        assert format_participant_name("Пупкин Вася", None) == "Пупкин Вася"

    def test_single_field_fedulov_rinat(self):
        assert format_participant_name("Федулов Ринат", None) == "Федулов Ринат"

    # single word — unchanged
    def test_single_word(self):
        assert format_participant_name("Алексей", None) == "Алексей"


class TestFamilyNameSortKey:
    def test_last_name_set(self):
        assert family_name_sort_key("Антон", "Ильин") == "ильин"

    def test_single_field_with_family_suffix(self):
        # "Оленин" looks like family name → sort by "оленин"
        assert family_name_sort_key("Дмитрий Оленин", None) == "оленин"

    def test_single_field_familiya_first(self):
        # "Ярослав" doesn't look like family name → sort by first word "кузнецов"
        assert family_name_sort_key("Кузнецов Ярослав", None) == "кузнецов"

    def test_single_word(self):
        assert family_name_sort_key("Мария", None) == "мария"

    def test_none(self):
        assert family_name_sort_key(None, None) == ""


class TestParticipantSortOrder:
    """Integration: _sort_participants puts unfilled first, then alphabetical by family name."""

    def test_sort_order(self, db, svc, user_svc, arch_svc):
        t = svc.create_tournament(TournamentCreate(title="T", chat_id=500, slug="t"))
        arch = arch_svc.get_or_create_by_name("Burn")

        # Unfilled
        u_unfilled = user_svc.get_or_create(tg_id=9001, first_name="Антон", last_name="Ильин")
        db.add(models.Participant(tournament_id=t.id, user_id=u_unfilled.id))

        # Split name
        u_split = user_svc.get_or_create(tg_id=9002, first_name="Мария", last_name="Аверина")
        db.add(models.Participant(tournament_id=t.id, user_id=u_split.id, archetype_id=arch.id))

        # Single-field "Имя Фамилия" (should sort by last word)
        u_single_ima = user_svc.get_or_create(tg_id=9003, first_name="Дмитрий Оленин")
        db.add(models.Participant(tournament_id=t.id, user_id=u_single_ima.id, archetype_id=arch.id))

        # Single-field "Фамилия Имя" (should sort by first word)
        u_single_fam = user_svc.get_or_create(tg_id=9004, first_name="Кузнецов Ярослав")
        db.add(models.Participant(tournament_id=t.id, user_id=u_single_fam.id, archetype_id=arch.id))

        db.commit()

        participants = svc.list_participants_for_tournament(t.id)
        sorted_p = _sort_participants(participants)

        # Unfilled first
        assert sorted_p[0].user.last_name == "Ильин"
        # Among filled: Аверина < Кузнецов < Оленин
        filled = [p for p in sorted_p if p.archetype]
        family_names = [family_name_sort_key(p.user.first_name, p.user.last_name) for p in filled]
        assert family_names == sorted(family_names)
