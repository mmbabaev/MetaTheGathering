from bot.keyboards import (
    tournament_list_keyboard,
    register_button,
    archetype_keyboard,
    CB_TOURNAMENT,
    CB_REGISTER,
    CB_ARCHETYPE,
    CB_CUSTOM_ARCHETYPE,
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
        assert len(markup.inline_keyboard) == 3  # 2 архетипа + «Свой вариант»

    def test_archetype_callback_data_format(self):
        markup = archetype_keyboard(10, [(5, "Burn")])
        cb = markup.inline_keyboard[0][0].callback_data
        assert cb == f"{CB_ARCHETYPE}:10:5"

    def test_custom_archetype_button_last(self):
        markup = archetype_keyboard(10, [(1, "Burn"), (2, "Affinity")])
        last_cb = markup.inline_keyboard[-1][0].callback_data
        assert last_cb == f"{CB_CUSTOM_ARCHETYPE}:10"

    def test_callback_data_under_64_bytes(self):
        # Telegram ограничение на callback_data — 64 байта
        markup = archetype_keyboard(99999, [(99999, "Burn")])
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64
