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
CB_EXPORT_EXCEL = "export_excel"          # export_excel:{tournament_id}
CB_DELETE_TOURNAMENT = "del_t"           # del_t:{tournament_id}
CB_DELETE_TOURNAMENT_CONFIRM = "del_t_yes"  # del_t_yes:{tournament_id}
CB_DELETE_TOURNAMENT_CANCEL = "del_t_no"    # del_t_no:{tournament_id}
CB_ADMIN_SHOW_FILLED = "adm_show_filled"    # adm_show_filled:{tournament_id}
CB_REVEAL_DECKS = "reveal_decks"            # reveal_decks:{tournament_id}
CB_POLL_MENU = "poll_menu"                  # poll_menu:{tournament_id}
CB_LINK_POLL_BY_URL = "link_poll_url"       # link_poll_url:{tournament_id}
CB_CREATE_POLL = "create_poll"              # create_poll:{tournament_id}
CB_NOTIFY_NO_DECK = "notify_no_deck"        # notify_no_deck:{tournament_id}
CB_NOTIFY_CONFIRM = "notify_confirm"        # notify_confirm:{tournament_id}
CB_NOTIFY_CANCEL = "notify_cancel"          # notify_cancel:{tournament_id}


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
    decks_hidden: bool = True,
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
        if decks_hidden:
            rows.append([
                InlineKeyboardButton(
                    "👁 Показать колоды", callback_data=f"{CB_REVEAL_DECKS}:{tournament_id}"
                )
            ])
        rows.append([
            InlineKeyboardButton(
                "➕ Добавить участников", callback_data=f"{CB_BULK_ADD}:{tournament_id}"
            )
        ])
        rows.append([
            InlineKeyboardButton(
                "📊 Опрос", callback_data=f"{CB_POLL_MENU}:{tournament_id}"
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                "📊 Выгрузка Excel", callback_data=f"{CB_EXPORT_EXCEL}:{tournament_id}"
            ),
            InlineKeyboardButton(
                "🗑 Удалить", callback_data=f"{CB_DELETE_TOURNAMENT}:{tournament_id}"
            ),
        ])
    return InlineKeyboardMarkup(rows)


def delete_tournament_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления турнира."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Да, удалить", callback_data=f"{CB_DELETE_TOURNAMENT_CONFIRM}:{tournament_id}"
        ),
        InlineKeyboardButton(
            "❌ Отмена", callback_data=f"{CB_DELETE_TOURNAMENT_CANCEL}:{tournament_id}"
        ),
    ]])


def register_button(tournament_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка «Записаться» для турнира (обратная совместимость)."""
    return tournament_card_keyboard(tournament_id, is_registered=False)


def fill_deck_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    """Кнопка в DM-уведомлении — ведёт сразу к выбору колоды."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🃏 Выбрать колоду", callback_data=f"{CB_REGISTER}:{tournament_id}")
    ]])


def poll_menu_keyboard(tournament_id: int, poll_link: str | None = None) -> InlineKeyboardMarkup:
    """Подменю «📊 Опрос»: создать / перейти (или привязать) / разослать / назад."""
    rows = [
        [InlineKeyboardButton("➕ Создать новый опрос", callback_data=f"{CB_CREATE_POLL}:{tournament_id}")],
    ]
    if poll_link:
        rows.append([InlineKeyboardButton("🔗 Перейти на последний опрос", url=poll_link)])
    else:
        rows.append([InlineKeyboardButton(
            "🔗 Привязать опрос по ссылке", callback_data=f"{CB_LINK_POLL_BY_URL}:{tournament_id}"
        )])
    rows.append([
        InlineKeyboardButton("📣 Напомнить без колоды", callback_data=f"{CB_NOTIFY_NO_DECK}:{tournament_id}")
    ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")
    ])
    return InlineKeyboardMarkup(rows)


def notify_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    """Подтверждение рассылки DM игрокам без колоды."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить", callback_data=f"{CB_NOTIFY_CONFIRM}:{tournament_id}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_NOTIFY_CANCEL}:{tournament_id}"),
    ]])


def leave_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    """Кнопки подтверждения выхода из турнира."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, выйти", callback_data=f"{CB_LEAVE_CONFIRM}:{tournament_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_LEAVE_CANCEL}:{tournament_id}"),
        ]
    ])


def settings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)]]
    return InlineKeyboardMarkup(rows)


def admin_participants_keyboard(
    participants: list,
    tournament_id: int | None = None,
    show_filled: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки участников для редактирования колоды (admin status view).

    По умолчанию показывает только незаполненных + кнопку «Показать заполненных (N)».
    При show_filled=True показывает всех участников.
    """
    unfilled = [p for p in participants if p.archetype is None]
    filled = [p for p in participants if p.archetype is not None]

    to_show = participants if show_filled else unfilled
    buttons = []
    for p in to_show:
        if p.user:
            from bot.messages import format_participant_name
            name = format_participant_name(p.user.first_name, p.user.last_name) or f"id{p.user.tg_id}"
        else:
            name = f"id{p.id}"
        prefix = "📝 " if p.archetype is None else "✏️ "
        buttons.append([
            InlineKeyboardButton(f"{prefix}{name}", callback_data=f"{CB_ADMIN_PICK_ARCH}:{p.id}")
        ])

    if not show_filled and filled and tournament_id is not None:
        buttons.append([
            InlineKeyboardButton(
                f"Показать заполненных ({len(filled)})",
                callback_data=f"{CB_ADMIN_SHOW_FILLED}:{tournament_id}",
            )
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
    from bot.deck_emoji import deck_emoji
    buttons = [
        [InlineKeyboardButton(deck_emoji.format(name), callback_data=f"{CB_ADMIN_SET_ARCH}:{participant_id}:{aid}")]
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
