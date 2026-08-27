import pytest

from bot.deck_emoji import deck_emoji
from bot.features import FeatureService
from bot.keyboards import (
    CB_ADMIN_ARCH_MORE,
    CB_ADMIN_CUSTOM_ARCH,
    CB_ADMIN_SET_ARCH,
    CB_ARCHETYPE,
    CB_ARCHETYPE_MORE,
    CB_CUSTOM_ARCHETYPE,
    CB_DEBUG_META_POLICE,
    CB_REGISTER,
    CB_REOPEN_TOURNAMENT,
    CB_TOURNAMENT,
    Keyboards,
    admin_archetype_select_keyboard,
    archetype_keyboard,
    register_button,
    tournament_card_keyboard,
    tournament_list_keyboard,
)


class TestTournamentListKeyboard:
    def test_one_button_per_tournament(self):
        markup = tournament_list_keyboard([(1, "Cup A"), (2, "Cup B")])
        assert len(markup.inline_keyboard) == 2

    def test_callback_data_format(self):
        markup = tournament_list_keyboard([(42, "Cup")])
        cb = markup.inline_keyboard[0][0].callback_data
        assert cb == f"{CB_TOURNAMENT}:42"

    def test_button_label_is_title(self):
        markup = tournament_list_keyboard([(1, "Pauper Friday")])
        assert markup.inline_keyboard[0][0].text == "Pauper Friday"

    def test_empty_list(self):
        markup = tournament_list_keyboard([])
        assert len(markup.inline_keyboard) == 0


class TestRegisterButton:
    def test_has_register_and_status_buttons(self):
        markup = register_button(7)
        # register_button delegates to tournament_card_keyboard(unregistered) → 2 rows
        assert len(markup.inline_keyboard) == 2

    def test_callback_data_format(self):
        markup = register_button(7)
        cb = markup.inline_keyboard[0][0].callback_data
        assert cb == f"{CB_REGISTER}:7"


class TestArchetypeKeyboard:
    def test_one_button_per_archetype_plus_custom(self):
        archetypes = [(1, "Burn"), (2, "Affinity")]
        markup = archetype_keyboard(10, archetypes)
        assert len(markup.inline_keyboard) == 4  # 2 архетипа + «Свой вариант» + «Назад»

    def test_archetype_callback_data_format(self):
        markup = archetype_keyboard(10, [(5, "Burn")])
        cb = markup.inline_keyboard[0][0].callback_data
        assert cb == f"{CB_ARCHETYPE}:10:5"

    def test_custom_archetype_button_second_to_last(self):
        markup = archetype_keyboard(10, [(1, "Burn"), (2, "Affinity")])
        second_last_cb = markup.inline_keyboard[-2][0].callback_data
        assert second_last_cb == f"{CB_CUSTOM_ARCHETYPE}:10"

    def test_back_button_last(self):
        markup = archetype_keyboard(10, [(1, "Burn")])
        last_cb = markup.inline_keyboard[-1][0].callback_data
        assert last_cb == f"{CB_TOURNAMENT}:10"

    def test_callback_data_under_64_bytes(self):
        # Telegram ограничение на callback_data — 64 байта
        markup = archetype_keyboard(99999, [(99999, "Burn")])
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64

    def test_known_deck_label_includes_emoji(self):
        markup = archetype_keyboard(10, [(1, "Red Kuldotha")])
        label = markup.inline_keyboard[0][0].text
        assert label == deck_emoji.format("Red Kuldotha")
        assert "🔴" in label

    def test_unknown_deck_label_is_plain_name(self):
        markup = archetype_keyboard(10, [(1, "Unknown Brew")])
        label = markup.inline_keyboard[0][0].text
        assert label == "Unknown Brew"

    def test_has_more_button_present_when_flag_true(self):
        markup = archetype_keyboard(10, [(1, "Burn")], has_more=True)
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ARCHETYPE_MORE) for cb in cbs)

    def test_no_more_button_when_flag_false(self):
        markup = archetype_keyboard(10, [(1, "Burn")], has_more=False)
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ARCHETYPE_MORE) for cb in cbs)


class TestAdminArchetypeSelectKeyboard:
    def test_one_button_per_archetype_plus_custom(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Burn"), (2, "Elves")])
        arch_btns = [b for row in markup.inline_keyboard for b in row if b.callback_data.startswith(CB_ADMIN_SET_ARCH)]
        assert len(arch_btns) == 2

    def test_callback_data_format(self):
        markup = admin_archetype_select_keyboard(5, [(7, "Burn")])
        cb = markup.inline_keyboard[0][0].callback_data
        assert cb == f"{CB_ADMIN_SET_ARCH}:5:7"

    def test_custom_button_last(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Burn")])
        last_cb = markup.inline_keyboard[-1][0].callback_data
        assert last_cb.startswith(CB_ADMIN_CUSTOM_ARCH)

    def test_known_deck_label_includes_emoji(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Blue Faeries")])
        label = markup.inline_keyboard[0][0].text
        assert label == deck_emoji.format("Blue Faeries")
        assert "🔵" in label

    def test_unknown_deck_label_is_plain_name(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Some Brew")])
        label = markup.inline_keyboard[0][0].text
        assert label == "Some Brew"

    def test_has_more_button_when_flag_true(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Burn")], has_more=True)
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert any(cb.startswith(CB_ADMIN_ARCH_MORE) for cb in cbs)

    def test_no_more_button_when_flag_false(self):
        markup = admin_archetype_select_keyboard(5, [(1, "Burn")], has_more=False)
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert not any(cb.startswith(CB_ADMIN_ARCH_MORE) for cb in cbs)

    def test_callback_data_under_64_bytes(self):
        markup = admin_archetype_select_keyboard(99999, [(99999, "Burn")])
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64


class TestTournamentCardKeyboard:
    def _all_texts(self, markup):
        return [b.text for row in markup.inline_keyboard for b in row]

    def test_registered_without_deck_shows_choose_deck_button(self):
        markup = tournament_card_keyboard(1, is_registered=True, has_deck=False)
        texts = self._all_texts(markup)
        assert any("Выбрать колоду" in t for t in texts)

    def test_registered_with_deck_no_choose_deck_button(self):
        markup = tournament_card_keyboard(1, is_registered=True, has_deck=True)
        texts = self._all_texts(markup)
        assert not any("Выбрать колоду" in t for t in texts)

    def test_unregistered_no_choose_deck_button(self):
        markup = tournament_card_keyboard(1, is_registered=False, has_deck=False)
        texts = self._all_texts(markup)
        assert not any("Выбрать колоду" in t for t in texts)

    def test_aetherhub_url_stored_shows_refresh_emoji(self):
        markup = tournament_card_keyboard(
            1, is_registered=False, is_admin=True, aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/1"
        )
        texts = self._all_texts(markup)
        assert any("🔄" in t and "AetherHub" in t for t in texts)

    def test_no_aetherhub_url_shows_import_emoji(self):
        markup = tournament_card_keyboard(1, is_registered=False, is_admin=True)
        texts = self._all_texts(markup)
        assert any("📥" in t and "AetherHub" in t for t in texts)

    def test_opponents_button_shown_when_enabled(self):
        markup = Keyboards().tournament_card_keyboard(1, is_registered=True, show_fill_opponents=True)
        texts = self._all_texts(markup)
        assert any("оппонент" in t.lower() for t in texts)

    def test_opponents_button_hidden_when_not_enabled(self):
        markup = Keyboards().tournament_card_keyboard(1, is_registered=True, show_fill_opponents=False)
        texts = self._all_texts(markup)
        assert not any("оппонент" in t.lower() for t in texts)

    def test_opponents_button_shown_without_deck(self):
        markup = Keyboards().tournament_card_keyboard(1, is_registered=True, show_fill_opponents=True, has_deck=False)
        texts = self._all_texts(markup)
        assert any("оппонент" in t.lower() for t in texts)

    def test_opponents_button_hidden_when_not_registered(self):
        markup = Keyboards().tournament_card_keyboard(1, is_registered=False, show_fill_opponents=True)
        texts = self._all_texts(markup)
        assert not any("оппонент" in t.lower() for t in texts)

    def test_debug_meta_police_button_is_explicitly_gated(self):
        hidden = tournament_card_keyboard(1, is_registered=False)
        shown = tournament_card_keyboard(1, is_registered=False, show_debug_meta_police=True)

        assert not any(
            button.callback_data == f"{CB_DEBUG_META_POLICE}:1" for row in hidden.inline_keyboard for button in row
        )
        assert any(
            button.callback_data == f"{CB_DEBUG_META_POLICE}:1" for row in shown.inline_keyboard for button in row
        )


# ── admin_more_keyboard: кнопка «Сделать активным» ───────────────────────────


class TestAdminMoreReopenButton:
    def _rows(self, kb):
        return [[b.text for b in row] for row in kb.inline_keyboard]

    def _flat(self, kb):
        return [b for row in kb.inline_keyboard for b in row]

    def test_reopen_shown_only_for_closed(self):
        kb_open = Keyboards().admin_more_keyboard(7, is_closed=False)
        assert not any("Сделать активным" in b.text for b in self._flat(kb_open))

        kb_closed = Keyboards().admin_more_keyboard(7, is_closed=True)
        assert any("Сделать активным" in b.text for b in self._flat(kb_closed))

    def test_reopen_sits_above_delete(self):
        rows = self._rows(Keyboards().admin_more_keyboard(7, is_closed=True))
        reopen_i = next(i for i, r in enumerate(rows) if any("Сделать активным" in t for t in r))
        delete_i = next(i for i, r in enumerate(rows) if any("Удалить турнир" in t for t in r))
        assert reopen_i == delete_i - 1

    def test_reopen_callback_data(self):
        btn = next(
            b for b in self._flat(Keyboards().admin_more_keyboard(42, is_closed=True)) if "Сделать активным" in b.text
        )
        assert btn.callback_data == f"{CB_REOPEN_TOURNAMENT}:42"
