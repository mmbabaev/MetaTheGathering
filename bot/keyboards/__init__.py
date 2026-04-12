# Inline клавиатуры

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Callback data prefixes (max 64 bytes in Telegram)
CB_REGISTER = "reg"
CB_ARCHETYPE = "arch"
CB_CUSTOM_ARCHETYPE = "custom"
CB_TOURNAMENT = "t"
CB_SETTINGS_NAME = "settings_name"


def tournament_list_keyboard(tournaments: list) -> InlineKeyboardMarkup:
    """Кнопки выбора турнира (id, title). tournaments: list of (id, title)."""
    buttons = [
        [InlineKeyboardButton(title, callback_data=f"{CB_TOURNAMENT}:{tid}")]
        for tid, title in tournaments
    ]
    return InlineKeyboardMarkup(buttons)


def register_button(tournament_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка «Записаться» для турнира."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Записаться", callback_data=f"{CB_REGISTER}:{tournament_id}")]
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    """Меню настроек пользователя."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)]
    ])


def archetype_keyboard(tournament_id: int, archetypes: list) -> InlineKeyboardMarkup:
    """Кнопки архетипов + «Свой вариант». archetypes: list of (id, name)."""
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"{CB_ARCHETYPE}:{tournament_id}:{aid}")]
        for aid, name in archetypes
    ]
    buttons.append([
        InlineKeyboardButton("Свой вариант", callback_data=f"{CB_CUSTOM_ARCHETYPE}:{tournament_id}")
    ])
    return InlineKeyboardMarkup(buttons)
