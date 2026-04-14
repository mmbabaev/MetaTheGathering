# Inline клавиатуры

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Callback data prefixes (max 64 bytes in Telegram)
CB_REGISTER = "reg"
CB_ARCHETYPE = "arch"
CB_CUSTOM_ARCHETYPE = "custom"
CB_ARCHETYPE_MORE = "arch_more"          # arch_more:{tournament_id}
CB_TOURNAMENT = "t"
CB_SETTINGS_NAME = "settings_name"
CB_TSTATUS = "tstatus"
CB_LEAVE = "leave"
CB_LEAVE_CONFIRM = "leave_confirm"
CB_LEAVE_CANCEL = "leave_cancel"
CB_BULK_ADD = "bulk_add"
CB_ADMIN_PICK_ARCH = "adm_pick"          # adm_pick:{participant_id}
CB_ADMIN_SET_ARCH = "adm_set"            # adm_set:{participant_id}:{archetype_id}
CB_ADMIN_CUSTOM_ARCH = "adm_custom"      # adm_custom:{participant_id}
CB_ADMIN_ARCH_MORE = "adm_arch_more"     # adm_arch_more:{participant_id}


def tournament_list_keyboard(tournaments: list) -> InlineKeyboardMarkup:
    """Кнопки выбора турнира (id, title). tournaments: list of (id, title)."""
    buttons = [
        [InlineKeyboardButton(title, callback_data=f"{CB_TOURNAMENT}:{tid}")]
        for tid, title in tournaments
    ]
    return InlineKeyboardMarkup(buttons)


def tournament_card_keyboard(
    tournament_id: int,
    is_registered: bool,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки для карточки турнира — зависят от статуса регистрации и роли пользователя."""
    if is_registered:
        action_btn = InlineKeyboardButton(
            "🚪 Выйти из турнира", callback_data=f"{CB_LEAVE}:{tournament_id}"
        )
    else:
        action_btn = InlineKeyboardButton(
            "Записаться", callback_data=f"{CB_REGISTER}:{tournament_id}"
        )
    status_btn = InlineKeyboardButton(
        "📋 Статус", callback_data=f"{CB_TSTATUS}:{tournament_id}"
    )
    rows = [[action_btn], [status_btn]]
    if is_admin:
        rows.append([
            InlineKeyboardButton(
                "➕ Добавить участников", callback_data=f"{CB_BULK_ADD}:{tournament_id}"
            )
        ])
    return InlineKeyboardMarkup(rows)


def register_button(tournament_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка «Записаться» для турнира (обратная совместимость)."""
    return tournament_card_keyboard(tournament_id, is_registered=False)


def leave_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    """Кнопки подтверждения выхода из турнира."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, выйти", callback_data=f"{CB_LEAVE_CONFIRM}:{tournament_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_LEAVE_CANCEL}:{tournament_id}"),
        ]
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    """Меню настроек пользователя."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)]
    ])


def admin_participants_keyboard(participants: list) -> InlineKeyboardMarkup:
    """Кнопка на каждого участника для редактирования колоды (admin status view)."""
    buttons = []
    for p in participants:
        if p.user:
            name_parts = [n for n in (p.user.first_name, p.user.last_name) if n]
            name = " ".join(name_parts) if name_parts else f"id{p.user.tg_id}"
        else:
            name = f"id{p.id}"
        prefix = "📝 " if p.archetype is None else "✏️ "
        buttons.append([
            InlineKeyboardButton(f"{prefix}{name}", callback_data=f"{CB_ADMIN_PICK_ARCH}:{p.id}")
        ])
    return InlineKeyboardMarkup(buttons)


def admin_archetype_select_keyboard(
    participant_id: int,
    archetypes: list,
    has_more: bool = False,
) -> InlineKeyboardMarkup:
    """Выбор архетипа для конкретного участника (admin flow).

    archetypes: list of (id, name).
    has_more: если True — добавляет кнопку «... ещё» перед «Свой вариант».
    """
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"{CB_ADMIN_SET_ARCH}:{participant_id}:{aid}")]
        for aid, name in archetypes
    ]
    if has_more:
        buttons.append([
            InlineKeyboardButton(
                "... ещё", callback_data=f"{CB_ADMIN_ARCH_MORE}:{participant_id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("Свой вариант", callback_data=f"{CB_ADMIN_CUSTOM_ARCH}:{participant_id}")
    ])
    return InlineKeyboardMarkup(buttons)


def archetype_keyboard(
    tournament_id: int,
    archetypes: list,
    has_more: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки архетипов + опционально «... ещё» + «Свой вариант».

    archetypes: list of (id, name).
    has_more: если True — добавляет кнопку «... ещё» перед «Свой вариант».
    """
    from bot.deck_emoji import deck_emoji
    buttons = [
        [InlineKeyboardButton(deck_emoji.format(name), callback_data=f"{CB_ARCHETYPE}:{tournament_id}:{aid}")]
        for aid, name in archetypes
    ]
    if has_more:
        buttons.append([
            InlineKeyboardButton(
                "... ещё", callback_data=f"{CB_ARCHETYPE_MORE}:{tournament_id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("Свой вариант", callback_data=f"{CB_CUSTOM_ARCHETYPE}:{tournament_id}")
    ])
    return InlineKeyboardMarkup(buttons)
