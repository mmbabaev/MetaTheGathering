# Inline клавиатуры

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.deck_emoji import deck_emoji
from bot.messages import format_participant_name

# Callback data prefixes (max 64 bytes in Telegram)
CB_REGISTER = "reg"
CB_ARCHETYPE = "arch"
CB_CUSTOM_ARCHETYPE = "custom"
CB_ARCHETYPE_MORE = "arch_more"  # arch_more:{tournament_id}
CB_TOURNAMENT = "t"
CB_SETTINGS_NAME = "settings_name"
CB_SETTINGS_TOGGLE_EMOJI = "settings_toggle_emoji"
CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY = "settings_toggle_opp_notify"
CB_SETTINGS_TOGGLE_STATUS_PAIRINGS = "settings_toggle_status_pairings"
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
CB_META_CHART = "meta_chart"  # meta_chart:{tournament_id}
CB_STANDINGS = "standings"  # standings:{tournament_id}
CB_EXPORT_MENU = "export_menu"  # export_menu:{tournament_id}
CB_EXPORT_PLAYERS = "export_players"  # export_players:{tournament_id}
CB_DELETE_TOURNAMENT = "del_t"  # del_t:{tournament_id}
CB_DELETE_TOURNAMENT_CONFIRM = "del_t_yes"  # del_t_yes:{tournament_id}
CB_DELETE_TOURNAMENT_CANCEL = "del_t_no"  # del_t_no:{tournament_id}
CB_ADMIN_SHOW_FILLED = "adm_show_filled"  # adm_show_filled:{tournament_id}
CB_REVEAL_DECKS = "reveal_decks"  # reveal_decks:{tournament_id}
CB_REVEAL_DECKS_CONFIRM = "reveal_decks_yes"  # reveal_decks_yes:{tournament_id}
CB_REVEAL_DECKS_CANCEL = "reveal_decks_no"  # reveal_decks_no:{tournament_id}
CB_HIDE_DECKS = "hide_decks"  # hide_decks:{tournament_id}
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
CB_ADMIN_PLAYER_ACTIONS = "adm_act"  # adm_act:{participant_id}:{tournament_id}
CB_ADMIN_REMOVE_CONFIRM = "adm_rm"  # adm_rm:{participant_id}:{tournament_id}
CB_ADMIN_REMOVE_DO = "adm_rm_do"  # adm_rm_do:{participant_id}:{tournament_id}
CB_ADMIN_SHOW_OPPONENTS = "adm_opps_p"  # adm_opps_p:{participant_id}:{tournament_id}
CB_ADMIN_TOGGLE_SCOREKEEPER = "adm_sk"  # adm_sk:{participant_id}:{tournament_id}
CB_CLOSE_TOURNAMENT = "close_t"  # close_t:{tournament_id}
CB_ADMIN_OPPONENTS = "adm_opps"  # adm_opps:{tournament_id}
CB_FEATURE_TOGGLE = "feat_toggle"  # feat_toggle:{flag_name}
CB_FEATURE_INFO = "feat_info"  # feat_info:{flag_name}
CB_PAY = "pay"  # pay:{tournament_id}
CB_PAY_STATUS = "pay_status"  # pay_status:{tournament_id} — no-op, показывает статус оплаты
CB_ADMIN_IMPORT_META = "adm_meta"  # adm_meta:{tournament_id}
CB_DEBUG_ROUND_NOTIFY = "dbg_rnotify"  # dbg_rnotify:{tournament_id} — debug: DM all round notifications to presser
CB_NOOP = "noop"  # мнимая кнопка (напр. номер стола): по нажатию просто гасим «часики»


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


@dataclass(frozen=True)
class StatusButton:
    """Чистая модель кнопки статуса (без зависимости от Telegram): подпись + callback."""

    label: str
    callback_data: str


def _status_participant_button(p) -> StatusButton:
    if p.user:
        name = format_participant_name(p.user.first_name, p.user.last_name) or f"id{p.user.tg_id}"
    else:
        name = f"id{p.id}"
    prefix = "📝 " if p.archetype is None else "✏️ "
    return StatusButton(f"{prefix}{name}", f"{CB_ADMIN_PICK_ARCH}:{p.id}")


def participant_button_rows(
    participants: list,
    tournament_id: int | None = None,
    show_filled: bool = False,
    pairs: list | None = None,
    unpaired: list | None = None,
) -> list[list[StatusButton]]:
    """Чистая модель клавиатуры участников статуса — ряды кнопок, без Telegram.

    С ``pairs`` (из ``pairing_rows``) — раскладка по столам: один ряд = один стол,
    две кнопки-игрока (бай/незарегистрированный игрок → одиночная кнопка), участники
    без пары — по двое в ряд; порядок строго по столам (как в ``pairs``). Без
    ``pairs`` — прежний плоский режим: только незаполненные, по одной кнопке в ряд,
    + «Показать заполненных». Telegram-слой лишь маппит это в InlineKeyboardMarkup.
    """
    back = [StatusButton("⬅️ Назад", f"{CB_TOURNAMENT}:{tournament_id}")] if tournament_id is not None else None

    if pairs is not None:
        rows: list[list[StatusButton]] = []
        for table, p1, _n1, p2, _n2 in pairs:
            players = [_status_participant_button(p) for p in (p1, p2) if p is not None]
            if not players:
                continue
            # Мнимая метка-заголовок стола ОТДЕЛЬНЫМ рядом над парой игроков (широкая, по центру) —
            # чтобы легче искать игроков по столу и не сплющивать кнопки в один ряд.
            if table is not None:
                rows.append([StatusButton(f"🎲 Стол №{table}", CB_NOOP)])
            rows.append(players)
        for i in range(0, len(unpaired or []), 2):
            rows.append([_status_participant_button(p) for p in (unpaired or [])[i : i + 2]])
        if back:
            rows.append(back)
        return rows

    unfilled = [p for p in participants if p.archetype is None]
    filled = [p for p in participants if p.archetype is not None]
    to_show = participants if show_filled else unfilled
    rows = [[_status_participant_button(p)] for p in to_show]
    if not show_filled and filled and tournament_id is not None:
        rows.append([StatusButton(f"Показать заполненных ({len(filled)})", f"{CB_ADMIN_SHOW_FILLED}:{tournament_id}")])
    if back:
        rows.append(back)
    return rows


def opponent_button_rows(opponents: list) -> list[list[StatusButton]]:
    """Чистая модель клавиатуры «Записать оппонентов» — по кнопке в ряд, с номером раунда.

    ``opponents`` — список ``UnfilledOpponent`` (``.participant`` + ``.round_number``),
    уже отсортированный по раунду. Показываем тур, чтобы игрок опознал оппонента «по порядку».
    """
    rows: list[list[StatusButton]] = []
    for o in opponents:
        p = o.participant
        if p.user:
            name = format_participant_name(p.user.first_name, p.user.last_name) or f"id{p.user.tg_id}"
        else:
            name = f"id{p.id}"
        rows.append([StatusButton(f"Раунд {o.round_number}: 📝 {name}", f"{CB_ADMIN_PICK_ARCH}:{p.id}")])
    return rows


def _status_rows_to_markup(rows: list[list[StatusButton]]) -> InlineKeyboardMarkup:
    """Telegram-адаптер: чистая модель рядов → InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b.label, callback_data=b.callback_data) for b in row] for row in rows]
    )


class Keyboards:
    def tournament_list_keyboard(self, tournaments: list) -> InlineKeyboardMarkup:
        buttons = [[InlineKeyboardButton(title, callback_data=f"{CB_TOURNAMENT}:{tid}")] for tid, title in tournaments]
        return InlineKeyboardMarkup(buttons)

    def pay_keyboard(self, url: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("💳 Перейти к оплате", url=url)]])

    def tournament_card_keyboard(
        self,
        tournament_id: int,
        is_registered: bool,
        is_admin: bool = False,
        decks_hidden: bool = True,
        show_fill_opponents: bool = False,
        has_deck: bool = True,
        aetherhub_url: str | None = None,
        import_time: str | None = None,
        payment_enabled: bool = False,
        payment_confirmed: bool = False,
    ) -> InlineKeyboardMarkup:
        if is_registered:
            action_btn = InlineKeyboardButton("🚪 Выйти из турнира", callback_data=f"{CB_LEAVE}:{tournament_id}")
        else:
            action_btn = InlineKeyboardButton("Записаться", callback_data=f"{CB_REGISTER}:{tournament_id}")
        status_btn = InlineKeyboardButton("📋 Статус", callback_data=f"{CB_TSTATUS}:{tournament_id}")
        rows = [[action_btn], [status_btn]]
        if is_registered and not has_deck:
            rows.insert(1, [InlineKeyboardButton("🃏 Выбрать колоду", callback_data=f"{CB_REGISTER}:{tournament_id}")])
        if payment_enabled and is_registered:
            if payment_confirmed:
                rows.insert(1, [InlineKeyboardButton("✅ Оплачено", callback_data=f"{CB_PAY_STATUS}:{tournament_id}")])
            else:
                rows.insert(1, [InlineKeyboardButton("💳 Оплатить взнос", callback_data=f"{CB_PAY}:{tournament_id}")])
        if is_registered and show_fill_opponents:
            rows.append(
                [InlineKeyboardButton("🤝 Записать оппонентов", callback_data=f"{CB_ADMIN_OPPONENTS}:{tournament_id}")]
            )
        if is_admin:
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
                    InlineKeyboardButton("📈 Выгрузка", callback_data=f"{CB_EXPORT_MENU}:{tournament_id}"),
                    InlineKeyboardButton("• • •", callback_data=f"{CB_ADMIN_MORE}:{tournament_id}"),
                ]
            )
        return InlineKeyboardMarkup(rows)

    def export_menu_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊 Meta (Excel)", callback_data=f"{CB_EXPORT_EXCEL}:{tournament_id}")],
                [InlineKeyboardButton("🍩 График метагейма", callback_data=f"{CB_META_CHART}:{tournament_id}")],
                [InlineKeyboardButton("🏆 Итоговые стендинги", callback_data=f"{CB_STANDINGS}:{tournament_id}")],
                [InlineKeyboardButton("👥 Список игроков", callback_data=f"{CB_EXPORT_PLAYERS}:{tournament_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")],
            ]
        )

    def reveal_decks_confirm_keyboard(self, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_REVEAL_DECKS_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton("👁 Показать", callback_data=f"{CB_REVEAL_DECKS_CONFIRM}:{tournament_id}"),
                ]
            ]
        )

    def admin_more_keyboard(
        self,
        tournament_id: int,
        is_closed: bool = False,
        decks_hidden: bool = True,
        show_debug: bool = False,
    ) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton("➕ Добавить участников", callback_data=f"{CB_BULK_ADD}:{tournament_id}")],
            [InlineKeyboardButton("📋 Импорт по таблице", callback_data=f"{CB_ADMIN_IMPORT_META}:{tournament_id}")],
        ]
        if show_debug:
            rows.append(
                [InlineKeyboardButton("🐞 Тест оповещений", callback_data=f"{CB_DEBUG_ROUND_NOTIFY}:{tournament_id}")]
            )
        if decks_hidden:
            rows.append([InlineKeyboardButton("👁 Показать колоды", callback_data=f"{CB_REVEAL_DECKS}:{tournament_id}")])
        else:
            rows.append([InlineKeyboardButton("🙈 Скрыть колоды", callback_data=f"{CB_HIDE_DECKS}:{tournament_id}")])
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

    def settings_keyboard(
        self,
        is_admin: bool = False,
        hide_deck_emoji: bool = False,
        notify_opponent_rounds: bool = False,
        status_by_pairings: bool = False,
    ) -> InlineKeyboardMarkup:
        emoji_label = "🚫 Эмоджи колод: выкл" if hide_deck_emoji else "🎨 Эмоджи колод: вкл"
        notify_label = (
            "🔔 Уведомления об оппоненте: вкл" if notify_opponent_rounds else "🔕 Уведомления об оппоненте: выкл"
        )
        pairings_label = "👥 Статус по парингам: вкл" if status_by_pairings else "📋 Статус по парингам: выкл"
        rows = [
            [InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)],
            [InlineKeyboardButton(emoji_label, callback_data=CB_SETTINGS_TOGGLE_EMOJI)],
            [InlineKeyboardButton(notify_label, callback_data=CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY)],
            [InlineKeyboardButton(pairings_label, callback_data=CB_SETTINGS_TOGGLE_STATUS_PAIRINGS)],
        ]
        return InlineKeyboardMarkup(rows)

    def admin_participants_keyboard(
        self,
        participants: list,
        tournament_id: int | None = None,
        show_filled: bool = False,
        pairs: list | None = None,
        unpaired: list | None = None,
    ) -> InlineKeyboardMarkup:
        """Тонкий адаптер: строит чистую модель и маппит её в Telegram-разметку."""
        return _status_rows_to_markup(
            participant_button_rows(participants, tournament_id, show_filled, pairs, unpaired)
        )

    def opponents_keyboard(self, opponents: list) -> InlineKeyboardMarkup:
        """Клавиатура «Записать оппонентов»: кнопки с номером раунда, по порядку раундов."""
        return _status_rows_to_markup(opponent_button_rows(opponents))

    def admin_player_actions_keyboard(
        self,
        participant_id: int,
        tournament_id: int,
        is_admin: bool = True,
        has_pairings: bool = True,
        is_target_scorekeeper: bool = False,
        is_privileged: bool = True,
    ) -> InlineKeyboardMarkup:
        buttons = []
        if is_privileged:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "📝 Изменить колоду",
                        callback_data=f"{CB_ADMIN_PICK_ARCH}:{participant_id}",
                    )
                ]
            )
        if has_pairings:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "👥 Показать оппонентов",
                        callback_data=f"{CB_ADMIN_SHOW_OPPONENTS}:{participant_id}:{tournament_id}",
                    )
                ]
            )
        if is_admin:
            sk_label = "🧙 Снять метаписца" if is_target_scorekeeper else "🧙 Метаписец"
            buttons.append(
                [
                    InlineKeyboardButton(
                        sk_label,
                        callback_data=f"{CB_ADMIN_TOGGLE_SCOREKEEPER}:{participant_id}:{tournament_id}",
                    ),
                    InlineKeyboardButton(
                        "🗑 Удалить",
                        callback_data=f"{CB_ADMIN_REMOVE_CONFIRM}:{participant_id}:{tournament_id}",
                    ),
                ]
            )
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_ADMIN_PICK_ARCH}:{participant_id}")])
        return InlineKeyboardMarkup(buttons)

    def admin_opponents_keyboard(self, participant_id: int, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_ADMIN_PICK_ARCH}:{participant_id}")]]
        )

    def admin_remove_confirm_keyboard(self, participant_id: int, tournament_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_ADMIN_PICK_ARCH}:{participant_id}"),
                    InlineKeyboardButton(
                        "✅ Удалить", callback_data=f"{CB_ADMIN_REMOVE_DO}:{participant_id}:{tournament_id}"
                    ),
                ]
            ]
        )

    def admin_archetype_select_keyboard(
        self,
        participant_id: int,
        archetypes: list,
        has_more: bool = False,
        show_emoji: bool = True,
        tournament_id: int | None = None,
        is_admin: bool = False,
    ) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    deck_emoji.format(name) if show_emoji else name,
                    callback_data=f"{CB_ADMIN_SET_ARCH}:{participant_id}:{aid}",
                )
            ]
            for aid, name in archetypes
        ]
        if has_more:
            buttons.append(
                [InlineKeyboardButton("... ещё колоды", callback_data=f"{CB_ADMIN_ARCH_MORE}:{participant_id}")]
            )
        buttons.append([InlineKeyboardButton("Свой вариант", callback_data=f"{CB_ADMIN_CUSTOM_ARCH}:{participant_id}")])
        if is_admin and tournament_id is not None:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "☰ Меню",
                        callback_data=f"{CB_ADMIN_PLAYER_ACTIONS}:{participant_id}:{tournament_id}",
                    )
                ]
            )
        if tournament_id is not None:
            buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TSTATUS}:{tournament_id}")])
        return InlineKeyboardMarkup(buttons)

    def archetype_keyboard(
        self,
        tournament_id: int,
        archetypes: list,
        has_more: bool = False,
        show_emoji: bool = True,
    ) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    deck_emoji.format(name) if show_emoji else name,
                    callback_data=f"{CB_ARCHETYPE}:{tournament_id}:{aid}",
                )
            ]
            for aid, name in archetypes
        ]
        if has_more:
            buttons.append(
                [InlineKeyboardButton("... ещё колоды", callback_data=f"{CB_ARCHETYPE_MORE}:{tournament_id}")]
            )
        buttons.append([InlineKeyboardButton("Свой вариант", callback_data=f"{CB_CUSTOM_ARCHETYPE}:{tournament_id}")])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_TOURNAMENT}:{tournament_id}")])
        return InlineKeyboardMarkup(buttons)


_default = Keyboards()


def tournament_list_keyboard(tournaments: list) -> InlineKeyboardMarkup:
    return _default.tournament_list_keyboard(tournaments)


def tournament_card_keyboard(
    tournament_id: int,
    is_registered: bool,
    is_admin: bool = False,
    decks_hidden: bool = True,
    show_fill_opponents: bool = False,
    has_deck: bool = True,
    aetherhub_url: str | None = None,
    import_time: str | None = None,
    payment_enabled: bool = False,
    payment_confirmed: bool = False,
) -> InlineKeyboardMarkup:
    return _default.tournament_card_keyboard(
        tournament_id,
        is_registered,
        is_admin=is_admin,
        decks_hidden=decks_hidden,
        show_fill_opponents=show_fill_opponents,
        has_deck=has_deck,
        aetherhub_url=aetherhub_url,
        import_time=import_time,
        payment_enabled=payment_enabled,
        payment_confirmed=payment_confirmed,
    )


def export_menu_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.export_menu_keyboard(tournament_id)


def admin_more_keyboard(
    tournament_id: int, is_closed: bool = False, decks_hidden: bool = True, show_debug: bool = False
) -> InlineKeyboardMarkup:
    return _default.admin_more_keyboard(
        tournament_id, is_closed=is_closed, decks_hidden=decks_hidden, show_debug=show_debug
    )


def reveal_decks_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.reveal_decks_confirm_keyboard(tournament_id)


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


def settings_keyboard(
    is_admin: bool = False,
    hide_deck_emoji: bool = False,
    notify_opponent_rounds: bool = False,
    status_by_pairings: bool = False,
) -> InlineKeyboardMarkup:
    return _default.settings_keyboard(
        is_admin=is_admin,
        hide_deck_emoji=hide_deck_emoji,
        notify_opponent_rounds=notify_opponent_rounds,
        status_by_pairings=status_by_pairings,
    )


def admin_participants_keyboard(
    participants: list,
    tournament_id: int | None = None,
    show_filled: bool = False,
    pairs: list | None = None,
    unpaired: list | None = None,
) -> InlineKeyboardMarkup:
    return _default.admin_participants_keyboard(
        participants, tournament_id=tournament_id, show_filled=show_filled, pairs=pairs, unpaired=unpaired
    )


def admin_player_actions_keyboard(
    participant_id: int,
    tournament_id: int,
    is_admin: bool = True,
    has_pairings: bool = True,
    is_target_scorekeeper: bool = False,
    is_privileged: bool = True,
) -> InlineKeyboardMarkup:
    return _default.admin_player_actions_keyboard(
        participant_id,
        tournament_id,
        is_admin=is_admin,
        has_pairings=has_pairings,
        is_target_scorekeeper=is_target_scorekeeper,
        is_privileged=is_privileged,
    )


def admin_opponents_keyboard(participant_id: int, tournament_id: int) -> InlineKeyboardMarkup:
    return _default.admin_opponents_keyboard(participant_id, tournament_id)


def admin_remove_confirm_keyboard(participant_id: int, tournament_id: int) -> InlineKeyboardMarkup:
    return _default.admin_remove_confirm_keyboard(participant_id, tournament_id)


def admin_archetype_select_keyboard(
    participant_id: int,
    archetypes: list,
    has_more: bool = False,
    tournament_id: int | None = None,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    return _default.admin_archetype_select_keyboard(
        participant_id,
        archetypes,
        has_more=has_more,
        tournament_id=tournament_id,
        is_admin=is_admin,
    )


def archetype_keyboard(
    tournament_id: int,
    archetypes: list,
    has_more: bool = False,
) -> InlineKeyboardMarkup:
    return _default.archetype_keyboard(tournament_id, archetypes, has_more=has_more)
