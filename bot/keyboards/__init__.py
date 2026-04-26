# Inline клавиатуры

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.deck_emoji import deck_emoji
from bot.features import FeatureService
from bot.messages import format_participant_name

# Callback data prefixes (max 64 bytes in Telegram)
CB_REGISTER = "reg"
CB_ARCHETYPE = "arch"
CB_CUSTOM_ARCHETYPE = "custom"
CB_ARCHETYPE_MORE = "arch_more"  # arch_more:{tournament_id}
CB_TOURNAMENT = "t"
CB_SETTINGS_NAME = "settings_name"
CB_TSTATUS = "tstatus"
CB_LEAVE = "leave"
CB_LEAVE_CONFIRM = "leave_confirm"
CB_LEAVE_CANCEL = "leave_cancel"
CB_BULK_ADD = "bulk_add"
CB_ADMIN_PICK_ARCH = "adm_pick"  # adm_pick:{participant_id}
CB_ADMIN_SET_ARCH = "adm_set"  # adm_set:{participant_id}:{archetype_id}
CB_ADMIN_CUSTOM_ARCH = "adm_custom"  # adm_custom:{participant_id}
CB_ADMIN_ARCH_MORE = "adm_arch_more"  # adm_arch_more:{participant_id}
CB_EXPORT_EXCEL = "export_excel"  # export_excel:{tournament_id}
CB_DELETE_TOURNAMENT = "del_t"  # del_t:{tournament_id}
CB_DELETE_TOURNAMENT_CONFIRM = "del_t_yes"  # del_t_yes:{tournament_id}
CB_DELETE_TOURNAMENT_CANCEL = "del_t_no"  # del_t_no:{tournament_id}
CB_ADMIN_SHOW_FILLED = "adm_show_filled"  # adm_show_filled:{tournament_id}
CB_REVEAL_DECKS = "reveal_decks"  # reveal_decks:{tournament_id}
CB_POLL_MENU = "poll_menu"  # poll_menu:{tournament_id}
CB_LINK_POLL_BY_URL = "link_poll_url"  # link_poll_url:{tournament_id}
CB_CREATE_POLL = "create_poll"  # create_poll:{tournament_id}
CB_NOTIFY_NO_DECK = "notify_no_deck"  # notify_no_deck:{tournament_id}
CB_NOTIFY_CONFIRM = "notify_confirm"  # notify_confirm:{tournament_id}
CB_NOTIFY_CANCEL = "notify_cancel"  # notify_cancel:{tournament_id}
CB_AETHERHUB_IMPORT = "ah_import"  # ah_import:{tournament_id}
CB_AETHERHUB_CONFIRM = "ah_confirm"  # ah_confirm:{tournament_id}
CB_AETHERHUB_CANCEL = "ah_cancel"  # ah_cancel:{tournament_id}
CB_SET_IMPORT_TIME = "set_import_time"  # set_import_time:{tournament_id}
CB_ADMIN_MORE = "adm_more"  # adm_more:{tournament_id}
CB_CLOSE_TOURNAMENT = "close_t"  # close_t:{tournament_id}
CB_ADMIN_OPPONENTS = "adm_opps"  # adm_opps:{tournament_id}
CB_FEATURE_TOGGLE = "feat_toggle"  # feat_toggle:{flag_name}
CB_FEATURE_INFO = "feat_info"  # feat_info:{flag_name}


def features_keyboard(flags: list) -> InlineKeyboardMarkup:
    """Кнопки feature flags — каждый флаг как строка из двух кнопок: описание (алерт) + тогл."""
    buttons = []
    for flag in flags:
        status = "✅" if flag.enabled else "❌"
        buttons.append(
            [
                InlineKeyboardButton(flag.name, callback_data=f"{CB_FEATURE_INFO}:{flag.name}"),
                InlineKeyboardButton(status, callback_data=f"{CB_FEATURE_TOGGLE}:{flag.name}"),
            ]
        )
    return InlineKeyboardMarkup(buttons)


class Keyboards:
    def __init__(self, features: FeatureService) -> None:
        self._features = features

    def tournament_list_keyboard(self, tournaments: list) -> InlineKeyboardMarkup:
        buttons = [[InlineKeyboardButton(title, callback_data=f"{CB_TOURNAMENT}:{tid}")] for tid, title in tournaments]
        return InlineKeyboardMarkup(buttons)

    def tournament_card_keyboard(
        self,
        tournament_id: int,
        is_registered: bool,
        is_admin: bool = False,
        decks_hidden: bool = True,
        has_pairings: bool = False,
        has_deck: bool = True,
        aetherhub_url: str | None = None,
        import_time: str | None = None,
    ) -> InlineKeyboardMarkup:
        if is_registered:
            action_btn = InlineKeyboardButton("🚪 Выйти из турнира", callback_data=f"{CB_LEAVE}:{tournament_id}")
        else:
            action_btn = InlineKeyboardButton("Записаться", callback_data=f"{CB_REGISTER}:{tournament_id}")
        status_btn = InlineKeyboardButton("📋 Статус", callback_data=f"{CB_TSTATUS}:{tournament_id}")
        rows = [[action_btn], [status_btn]]
        if is_registered and not has_deck:
            rows.insert(1, [InlineKeyboardButton("🃏 Выбрать колоду", callback_data=f"{CB_REGISTER}:{tournament_id}")])
        if is_registered and has_pairings and self._features.can_fill_opponent_decks():
            rows.append(
                [InlineKeyboardButton("🤝 Записать оппонентов", callback_data=f"{CB_ADMIN_OPPONENTS}:{tournament_id}")]
            )
        if is_admin:
            if decks_hidden:
                rows.append(
                    [InlineKeyboardButton("👁 Показать колоды", callback_data=f"{CB_REVEAL_DECKS}:{tournament_id}")]
                )
            aetherhub_emoji = "🔄" if aetherhub_url else "📥"
            rows.append(
                [
                    InlineKeyboardButton("📊 Опрос", callback_data=f"{CB_POLL_MENU}:{tournament_id}"),
                    InlineKeyboardButton(
                        f"{aetherhub_emoji} AetherHub", callback_data=f"{CB_AETHERHUB_IMPORT}:{tournament_id}"
                    ),
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton("📈 Выгрузка Excel", callback_data=f"{CB_EXPORT_EXCEL}:{tournament_id}"),
                    InlineKeyboardButton("• • •", callback_data=f"{CB_ADMIN_MORE}:{tournament_id}"),
                ]
            )
        return InlineKeyboardMarkup(rows)

    def admin_more_keyboard(self, tournament_id: int, is_closed: bool = False) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton("➕ Добавить участников", callback_data=f"{CB_BULK_ADD}:{tournament_id}")],
        ]
        if not is_closed:
            rows.append(
                [InlineKeyboardButton("🔒 Закрыть турнир", callback_data=f"{CB_CLOSE_TOURNAMENT}:{tournament_id}")]
            )
        if is_closed:
            rows.append(
                [InlineKeyboardButton("🗑 Удалить турнир", callback_data=f"{CB_DELETE_TOURNAMENT}:{tournament_id}")]
            )
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")])
        return InlineKeyboardMarkup(rows)

    def delete_tournament_confirm_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_DELETE_TOURNAMENT_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton(
                        "✅ Да, удалить", callback_data=f"{CB_DELETE_TOURNAMENT_CONFIRM}:{tournament_id}"
                    ),
                ]
            ]
        )

    def register_button(self, tournament_id: int) -> InlineKeyboardMarkup:
        return self.tournament_card_keyboard(tournament_id, is_registered=False)

    def fill_deck_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🃏 Выбрать колоду", callback_data=f"{CB_REGISTER}:{tournament_id}")]]
        )

    def poll_menu_keyboard(self, tournament_id: int, poll_link: str | None = None) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton("➕ Создать новый опрос", callback_data=f"{CB_CREATE_POLL}:{tournament_id}")],
        ]
        if poll_link:
            rows.append([InlineKeyboardButton("🔗 Перейти на последний опрос", url=poll_link)])
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        "🔗 Привязать опрос по ссылке", callback_data=f"{CB_LINK_POLL_BY_URL}:{tournament_id}"
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton("📣 Напомнить без колоды", callback_data=f"{CB_NOTIFY_NO_DECK}:{tournament_id}")]
        )
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")])
        return InlineKeyboardMarkup(rows)

    def notify_confirm_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_NOTIFY_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton("✅ Отправить", callback_data=f"{CB_NOTIFY_CONFIRM}:{tournament_id}"),
                ]
            ]
        )

    def aetherhub_confirm_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_AETHERHUB_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton("✅ Импортировать", callback_data=f"{CB_AETHERHUB_CONFIRM}:{tournament_id}"),
                ]
            ]
        )

    def leave_confirm_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_LEAVE_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton("✅ Да, выйти", callback_data=f"{CB_LEAVE_CONFIRM}:{tournament_id}"),
                ]
            ]
        )

    def settings_keyboard(self, is_admin: bool = False) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)]]
        return InlineKeyboardMarkup(rows)

    def admin_participants_keyboard(
        self,
        participants: list,
        tournament_id: int | None = None,
        show_filled: bool = False,
    ) -> InlineKeyboardMarkup:
        unfilled = [p for p in participants if p.archetype is None]
        filled = [p for p in participants if p.archetype is not None]

        to_show = participants if show_filled else unfilled
        buttons = []
        for p in to_show:
            if p.user:
                name = format_participant_name(p.user.first_name, p.user.last_name) or f"id{p.user.tg_id}"
            else:
                name = f"id{p.id}"
            prefix = "📝 " if p.archetype is None else "✏️ "
            buttons.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f"{CB_ADMIN_PICK_ARCH}:{p.id}")])

        if not show_filled and filled and tournament_id is not None:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"Показать заполненных ({len(filled)})",
                        callback_data=f"{CB_ADMIN_SHOW_FILLED}:{tournament_id}",
                    )
                ]
            )

        return InlineKeyboardMarkup(buttons)

    def admin_archetype_select_keyboard(
        self,
        participant_id: int,
        archetypes: list,
        has_more: bool = False,
    ) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton(deck_emoji.format(name), callback_data=f"{CB_ADMIN_SET_ARCH}:{participant_id}:{aid}")]
            for aid, name in archetypes
        ]
        if has_more:
            buttons.append([InlineKeyboardButton("... ещё", callback_data=f"{CB_ADMIN_ARCH_MORE}:{participant_id}")])
        buttons.append([InlineKeyboardButton("Свой вариант", callback_data=f"{CB_ADMIN_CUSTOM_ARCH}:{participant_id}")])
        return InlineKeyboardMarkup(buttons)

    def archetype_keyboard(
        self,
        tournament_id: int,
        archetypes: list,
        has_more: bool = False,
    ) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton(deck_emoji.format(name), callback_data=f"{CB_ARCHETYPE}:{tournament_id}:{aid}")]
            for aid, name in archetypes
        ]
        if has_more:
            buttons.append([InlineKeyboardButton("... ещё", callback_data=f"{CB_ARCHETYPE_MORE}:{tournament_id}")])
        buttons.append([InlineKeyboardButton("Свой вариант", callback_data=f"{CB_CUSTOM_ARCHETYPE}:{tournament_id}")])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")])
        return InlineKeyboardMarkup(buttons)


# Module-level default instance — used by telegram layer and simple callers
from core.config import settings as _settings  # noqa: E402

_default = Keyboards(FeatureService(debug=_settings.DEBUG))


def tournament_list_keyboard(tournaments: list) -> InlineKeyboardMarkup:
    return _default.tournament_list_keyboard(tournaments)


def tournament_card_keyboard(
    tournament_id: int,
    is_registered: bool,
    is_admin: bool = False,
    decks_hidden: bool = True,
    has_pairings: bool = False,
    has_deck: bool = True,
    aetherhub_url: str | None = None,
    import_time: str | None = None,
) -> InlineKeyboardMarkup:
    return _default.tournament_card_keyboard(
        tournament_id,
        is_registered,
        is_admin=is_admin,
        decks_hidden=decks_hidden,
        has_pairings=has_pairings,
        has_deck=has_deck,
        aetherhub_url=aetherhub_url,
        import_time=import_time,
    )


def admin_more_keyboard(tournament_id: int, is_closed: bool = False) -> InlineKeyboardMarkup:
    return _default.admin_more_keyboard(tournament_id, is_closed=is_closed)


def delete_tournament_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.delete_tournament_confirm_keyboard(tournament_id)


def register_button(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.register_button(tournament_id)


def fill_deck_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.fill_deck_keyboard(tournament_id)


def poll_menu_keyboard(tournament_id: int, poll_link: str | None = None) -> InlineKeyboardMarkup:
    return _default.poll_menu_keyboard(tournament_id, poll_link=poll_link)


def notify_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.notify_confirm_keyboard(tournament_id)


def aetherhub_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.aetherhub_confirm_keyboard(tournament_id)


def leave_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.leave_confirm_keyboard(tournament_id)


def settings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    return _default.settings_keyboard(is_admin=is_admin)


def admin_participants_keyboard(
    participants: list,
    tournament_id: int | None = None,
    show_filled: bool = False,
) -> InlineKeyboardMarkup:
    return _default.admin_participants_keyboard(participants, tournament_id=tournament_id, show_filled=show_filled)


def admin_archetype_select_keyboard(
    participant_id: int,
    archetypes: list,
    has_more: bool = False,
) -> InlineKeyboardMarkup:
    return _default.admin_archetype_select_keyboard(participant_id, archetypes, has_more=has_more)


def archetype_keyboard(
    tournament_id: int,
    archetypes: list,
    has_more: bool = False,
) -> InlineKeyboardMarkup:
    return _default.archetype_keyboard(tournament_id, archetypes, has_more=has_more)
