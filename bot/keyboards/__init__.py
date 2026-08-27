# Inline клавиатуры

from dataclasses import dataclass
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.deck_emoji import deck_emoji
from bot.messages import format_participant_name
from services.schedule import WEEKDAY_RU, WEEKDAYS

# Callback data prefixes (max 64 bytes in Telegram)
CB_REGISTER = "reg"
CB_ARCHETYPE = "arch"
CB_CUSTOM_ARCHETYPE = "custom"
CB_ARCHETYPE_MORE = "arch_more"  # arch_more:{tournament_id}
CB_DEFER_DECK = "deck_later"  # deck_later:{tournament_id}
CB_FILL_MISSING_PICK = "fill_pick"  # fill_pick:{participant_id}
CB_FILL_MISSING_SET = "fill_set"  # fill_set:{participant_id}:{archetype_id}
CB_FILL_MISSING_MORE = "fill_more"  # fill_more:{participant_id}
CB_FILL_MISSING_CUSTOM = "fill_custom"  # fill_custom:{participant_id}
CB_TOURNAMENT = "t"
CB_SETTINGS_NAME = "settings_name"
CB_SETTINGS_TOGGLE_EMOJI = "settings_toggle_emoji"
CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY = "settings_toggle_opp_notify"
CB_SETTINGS_TOGGLE_ACHIEVEMENTS_NOTIFY = "settings_toggle_achievements_notify"
CB_SETTINGS_TOGGLE_POLL_NOTIFY = "settings_toggle_poll_notify"
CB_SETTINGS_TOGGLE_CELLAR_NOTIFY = "settings_toggle_cellar_notify"
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
CB_POLL_BROADCAST = "poll_bcast"  # poll_bcast:{tournament_id} — разослать подписчикам
CB_POLL_BROADCAST_CANCEL = "poll_bcast_no"  # poll_bcast_no:{tournament_id}
CB_POLL_ORG_MENU = "poll_org"  # poll_org — меню организатора: список клубов (фаза 3)
CB_POLL_CLUB = "poll_club"  # poll_club:{chat_id} — меню клуба (регуляры / ping)
CB_POLL_REGULARS = "poll_reg"  # poll_reg:{chat_id}:{page} — список регуляров (тумблеры)
CB_POLL_REGULAR_TOGGLE = "poll_reg_t"  # poll_reg_t:{chat_id}:{user_id}:{page} — вкл/выкл регуляра
CB_POLL_PING = "poll_ping"  # poll_ping:{chat_id} — «кому ещё написать»
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
CB_ADMIN_TOGGLE_POLL_ORGANIZER = "adm_po"  # adm_po:{participant_id}:{tournament_id}
CB_CLOSE_TOURNAMENT = "close_t"  # close_t:{tournament_id}
CB_REOPEN_TOURNAMENT = "reopen_t"  # reopen_t:{tournament_id} — вернуть закрытый турнир в регистрацию
CB_ADMIN_OPPONENTS = "adm_opps"  # adm_opps:{tournament_id}
CB_FEATURE_TOGGLE = "feat_toggle"  # feat_toggle:{flag_name}
CB_SCHEDULE_LIST = "sched_list"  # sched_list — список строк расписания (issue #124)
CB_SCHEDULE_ROW = "sched_row"  # sched_row:{row_id} — карточка одной строки
CB_SCHEDULE_TOGGLE = "sched_tgl"  # sched_tgl:{row_id} — включить/выключить строку
CB_SCHEDULE_EDIT_FIELD = "sched_ef"  # sched_ef:{row_id}:{field_idx} — правка времени (текстом)
CB_SCHEDULE_IMPORTS = "sched_imp"  # sched_imp:{row_id} — правка времён импорта
CB_SCHEDULE_WEEKDAY = "sched_wd"  # sched_wd:{row_id} — пикер дня недели
CB_SCHEDULE_SET_WEEKDAY = "sched_swd"  # sched_swd:{row_id}:{weekday_idx} — задать день недели
CB_FEATURE_INFO = "feat_info"  # feat_info:{flag_name}
CB_PAY = "pay"  # pay:{tournament_id}
CB_PAY_STATUS = "pay_status"  # pay_status:{tournament_id} — no-op, показывает статус оплаты
CB_ADMIN_IMPORT_META = "adm_meta"  # adm_meta:{tournament_id}
CB_DEBUG_ROUND_NOTIFY = "dbg_rnotify"  # dbg_rnotify:{tournament_id} — debug: DM all round notifications to presser
CB_DEBUG_META_POLICE = "dbg_mpol"  # dbg_mpol:{tournament_id} — debug: live preview only for owner
CB_APP_STATS_HOME = "appstat_home"  # appstat_home — меню статистики приложения (владелец)
CB_APP_STATS_NOTIFY_ROUNDS = "appstat_nr"  # appstat_nr — список включивших уведомления о раундах
CB_CELLAR_DATES = "cellar_dates"
CB_CELLAR_DATE = "cellar_date"  # cellar_date:{YYYY-MM-DD}:{page}
CB_CELLAR_DECK = "cellar_deck"  # cellar_deck:{YYYY-MM-DD}:{deck_id}:{page}
CB_CELLAR_RESERVE = "cellar_reserve"  # cellar_reserve:{YYYY-MM-DD}:{deck_id}:{page}
CB_CELLAR_CANCEL = "cellar_cancel"  # cellar_cancel:{reservation_id}:{page}
CB_CELLAR_CANCEL_CONFIRM = "cellar_cancel_yes"  # cellar_cancel_yes:{reservation_id}:{page}
CB_CELLAR_NOOP = "cellar_noop"

CELLAR_PAGE_SIZE = 10


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


def cellar_dates_keyboard(dates: list[date], web_url: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(event_date.strftime("%d.%m.%Y"), callback_data=f"{CB_CELLAR_DATE}:{event_date}:0")]
        for event_date in dates
    ]
    rows.append([InlineKeyboardButton("🌐 Открыть web-версию", url=web_url)])
    return InlineKeyboardMarkup(rows)


def _cellar_reservation_for(deck, event_date: date):
    return next(
        (
            reservation
            for reservation in deck.reservations
            if reservation.event_date == event_date and reservation.cancelled_at is None
        ),
        None,
    )


def cellar_catalog_keyboard(
    decks: list,
    *,
    event_date: date,
    user_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    page_count = max(1, (len(decks) + CELLAR_PAGE_SIZE - 1) // CELLAR_PAGE_SIZE)
    page = min(max(page, 0), page_count - 1)
    visible = decks[page * CELLAR_PAGE_SIZE : (page + 1) * CELLAR_PAGE_SIZE]
    rows = []
    for deck in visible:
        reservation = _cellar_reservation_for(deck, event_date)
        if not deck.available:
            prefix = "🚫 "
        elif reservation is None:
            prefix = "▫️ "
        elif reservation.user_id == user_id:
            prefix = "✅ "
        else:
            prefix = "🔒 "
        label = prefix + deck.display_name
        if len(label) > 56:
            label = label[:55] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{CB_CELLAR_DECK}:{event_date}:{deck.id}:{page}",
                )
            ]
        )

    if page_count > 1:
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton("⬅️", callback_data=f"{CB_CELLAR_DATE}:{event_date}:{page - 1}"))
        navigation.append(InlineKeyboardButton(f"{page + 1}/{page_count}", callback_data=CB_CELLAR_NOOP))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton("➡️", callback_data=f"{CB_CELLAR_DATE}:{event_date}:{page + 1}"))
        rows.append(navigation)
    rows.append([InlineKeyboardButton("⬅️ К датам", callback_data=CB_CELLAR_DATES)])
    return InlineKeyboardMarkup(rows)


def cellar_deck_keyboard(
    *,
    deck_id: int,
    event_date: date,
    page: int,
    decklist_url: str | None,
    can_reserve: bool,
    own_reservation_id: int | None,
) -> InlineKeyboardMarkup:
    rows = []
    if decklist_url:
        rows.append([InlineKeyboardButton("📄 Деклист и сайдборд", url=decklist_url)])
    if can_reserve:
        rows.append(
            [
                InlineKeyboardButton(
                    "✅ Забронировать",
                    callback_data=f"{CB_CELLAR_RESERVE}:{event_date}:{deck_id}:{page}",
                )
            ]
        )
    if own_reservation_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    "❌ Отменить бронь",
                    callback_data=f"{CB_CELLAR_CANCEL}:{own_reservation_id}:{page}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ К списку", callback_data=f"{CB_CELLAR_DATE}:{event_date}:{page}")])
    return InlineKeyboardMarkup(rows)


def cellar_cancel_keyboard(reservation_id: int, event_date: date, deck_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Да, отменить",
                    callback_data=f"{CB_CELLAR_CANCEL_CONFIRM}:{reservation_id}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Не отменять",
                    callback_data=f"{CB_CELLAR_DECK}:{event_date}:{deck_id}:{page}",
                )
            ],
        ]
    )


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
        for _table, p1, _n1, p2, _n2 in pairs:
            row = [_status_participant_button(p) for p in (p1, p2) if p is not None]
            if row:
                rows.append(row)
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


def missing_deck_button_rows(participants: list) -> list[list[StatusButton]]:
    """Кнопки только для участников без колоды в community-flow мета-полиции."""
    rows: list[list[StatusButton]] = []
    for participant in participants:
        if participant.archetype_id is not None:
            continue
        user = participant.user
        name = format_participant_name(user.first_name, user.last_name) or f"id{user.tg_id}"
        rows.append([StatusButton(f"📝 {name}", f"{CB_FILL_MISSING_PICK}:{participant.id}")])
    return rows


def _status_rows_to_markup(rows: list[list[StatusButton]]) -> InlineKeyboardMarkup:
    """Telegram-адаптер: чистая модель рядов → InlineKeyboardMarkup."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b.label, callback_data=b.callback_data) for b in row] for row in rows]
    )


class Keyboards:
    def missing_decks_keyboard(self, participants: list) -> InlineKeyboardMarkup:
        return _status_rows_to_markup(missing_deck_button_rows(participants))

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
        show_debug_meta_police: bool = False,
    ) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton("➕ Добавить участников", callback_data=f"{CB_BULK_ADD}:{tournament_id}")],
            [InlineKeyboardButton("📋 Импорт по таблице", callback_data=f"{CB_ADMIN_IMPORT_META}:{tournament_id}")],
        ]
        debug_buttons = []
        if show_debug:
            debug_buttons.append(
                InlineKeyboardButton("🐞 Тест оповещений", callback_data=f"{CB_DEBUG_ROUND_NOTIFY}:{tournament_id}")
            )
        if show_debug_meta_police:
            debug_buttons.append(
                InlineKeyboardButton("🐞 Мета-полиция", callback_data=f"{CB_DEBUG_META_POLICE}:{tournament_id}")
            )
        if debug_buttons:
            rows.append(debug_buttons)
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
                [InlineKeyboardButton("🔓 Сделать активным", callback_data=f"{CB_REOPEN_TOURNAMENT}:{tournament_id}")]
            )
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

    def poll_broadcast_keyboard(self, tournament_id: int, count: int) -> InlineKeyboardMarkup:
        """Аппрув рассылки уведомления о голосовании подписчикам."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("❌ Отмена", callback_data=f"{CB_POLL_BROADCAST_CANCEL}:{tournament_id}"),
                    InlineKeyboardButton(
                        f"📣 Разослать ({count})", callback_data=f"{CB_POLL_BROADCAST}:{tournament_id}"
                    ),
                ]
            ]
        )

    def poll_clubs_keyboard(self, clubs: list[tuple[int, str]]) -> InlineKeyboardMarkup:
        """Список клубов для меню организатора голосований (/poll)."""
        rows = [[InlineKeyboardButton(label, callback_data=f"{CB_POLL_CLUB}:{chat_id}")] for chat_id, label in clubs]
        return InlineKeyboardMarkup(rows)

    def poll_club_menu_keyboard(self, chat_id: int, regulars_count: int) -> InlineKeyboardMarkup:
        """Меню одного клуба: регуляры + «кому ещё написать»."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"👥 Регуляры ({regulars_count})", callback_data=f"{CB_POLL_REGULARS}:{chat_id}:0"
                    )
                ],
                [InlineKeyboardButton("📋 Кому ещё написать", callback_data=f"{CB_POLL_PING}:{chat_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=CB_POLL_ORG_MENU)],
            ]
        )

    def poll_regulars_keyboard(
        self,
        chat_id: int,
        players: list[tuple[int, str]],
        regular_ids: set[int],
        page: int,
        page_size: int = 8,
    ) -> InlineKeyboardMarkup:
        """Тумблеры кандидатов в регуляры (✅/⬜) с пагинацией. players: (user_id, label)."""
        start = page * page_size
        chunk = players[start : start + page_size]
        rows = []
        for user_id, label in chunk:
            mark = "✅" if user_id in regular_ids else "⬜️"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{mark} {label}",
                        callback_data=f"{CB_POLL_REGULAR_TOGGLE}:{chat_id}:{user_id}:{page}",
                    )
                ]
            )
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"{CB_POLL_REGULARS}:{chat_id}:{page - 1}"))
        if start + page_size < len(players):
            nav.append(InlineKeyboardButton("▶️", callback_data=f"{CB_POLL_REGULARS}:{chat_id}:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_POLL_CLUB}:{chat_id}")])
        return InlineKeyboardMarkup(rows)

    def app_stats_keyboard(self, notify_rounds: int) -> InlineKeyboardMarkup:
        """Меню статистики приложения: строка-метрика по тапу открывает список."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🔔 Уведомления о раундах: {notify_rounds}",
                        callback_data=CB_APP_STATS_NOTIFY_ROUNDS,
                    )
                ]
            ]
        )

    def app_stats_back_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CB_APP_STATS_HOME)]])

    def schedule_list_keyboard(self, rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
        """Список строк расписания: одна кнопка на строку. rows: (row_id, label)."""
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=f"{CB_SCHEDULE_ROW}:{row_id}")] for row_id, label in rows]
        )

    def schedule_row_keyboard(
        self,
        row_id: int,
        enabled: bool,
        create_time: str = "",
        game_time: str = "",
        reminder_time: str | None = None,
        imports_summary: str = "",
        weekday_ru: str = "",
    ) -> InlineKeyboardMarkup:
        """Карточка строки расписания: правка времён/дня/импортов + тумблер + назад."""
        toggle_label = "⏸ Выключить" if enabled else "▶️ Включить"
        reminder_label = reminder_time or "выкл"
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🕐 Создание: {create_time}", callback_data=f"{CB_SCHEDULE_EDIT_FIELD}:{row_id}:0"
                    )
                ],
                [InlineKeyboardButton(f"🎮 Игра: {game_time}", callback_data=f"{CB_SCHEDULE_EDIT_FIELD}:{row_id}:1")],
                [
                    InlineKeyboardButton(
                        f"🔔 Напоминание: {reminder_label}", callback_data=f"{CB_SCHEDULE_EDIT_FIELD}:{row_id}:2"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"🔄 Импорты: {imports_summary}", callback_data=f"{CB_SCHEDULE_IMPORTS}:{row_id}"
                    )
                ],
                [InlineKeyboardButton(f"📆 День: {weekday_ru}", callback_data=f"{CB_SCHEDULE_WEEKDAY}:{row_id}")],
                [InlineKeyboardButton(toggle_label, callback_data=f"{CB_SCHEDULE_TOGGLE}:{row_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=CB_SCHEDULE_LIST)],
            ]
        )

    def schedule_weekday_keyboard(self, row_id: int, current_weekday: str) -> InlineKeyboardMarkup:
        """Пикер дня недели: 7 кнопок (текущий помечен), по 2 в ряд, + назад к карточке."""
        buttons = []
        for idx, wd in enumerate(WEEKDAYS):
            mark = "✅ " if wd == current_weekday else ""
            buttons.append(
                InlineKeyboardButton(
                    f"{mark}{WEEKDAY_RU[wd]}", callback_data=f"{CB_SCHEDULE_SET_WEEKDAY}:{row_id}:{idx}"
                )
            )
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{CB_SCHEDULE_ROW}:{row_id}")])
        return InlineKeyboardMarkup(rows)

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
        notify_achievements: bool = False,
        notify_poll: bool = False,
        notify_cellar_reservations: bool | None = None,
        status_by_pairings: bool = False,
    ) -> InlineKeyboardMarkup:
        emoji_label = "🚫 Эмоджи колод: выкл" if hide_deck_emoji else "🎨 Эмоджи колод: вкл"
        notify_label = (
            "🔔 Уведомления об оппоненте: вкл" if notify_opponent_rounds else "🔕 Уведомления об оппоненте: выкл"
        )
        poll_label = "🔔 Уведомления о голосованиях: вкл" if notify_poll else "🔕 Уведомления о голосованиях: выкл"
        achievements_label = (
            "🔔 Уведомления об ачивках: вкл" if notify_achievements else "🔕 Уведомления об ачивках: выкл"
        )
        pairings_label = "👥 Статус по парингам: вкл" if status_by_pairings else "📋 Статус по парингам: выкл"
        rows = [
            [InlineKeyboardButton("✏️ Изменить имя", callback_data=CB_SETTINGS_NAME)],
            [InlineKeyboardButton(emoji_label, callback_data=CB_SETTINGS_TOGGLE_EMOJI)],
            [InlineKeyboardButton(notify_label, callback_data=CB_SETTINGS_TOGGLE_OPPONENT_NOTIFY)],
            [InlineKeyboardButton(achievements_label, callback_data=CB_SETTINGS_TOGGLE_ACHIEVEMENTS_NOTIFY)],
            [InlineKeyboardButton(poll_label, callback_data=CB_SETTINGS_TOGGLE_POLL_NOTIFY)],
        ]
        if notify_cellar_reservations is not None:
            cellar_label = (
                "🔔 Уведомления о ячейках: вкл" if notify_cellar_reservations else "🔕 Уведомления о ячейках: выкл"
            )
            rows.append([InlineKeyboardButton(cellar_label, callback_data=CB_SETTINGS_TOGGLE_CELLAR_NOTIFY)])
        rows.append([InlineKeyboardButton(pairings_label, callback_data=CB_SETTINGS_TOGGLE_STATUS_PAIRINGS)])
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
        is_target_poll_organizer: bool = False,
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
            po_label = "📊 Снять организатора" if is_target_poll_organizer else "📊 Организатор голосований"
            buttons.append(
                [
                    InlineKeyboardButton(
                        po_label,
                        callback_data=f"{CB_ADMIN_TOGGLE_POLL_ORGANIZER}:{participant_id}:{tournament_id}",
                    )
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

    def missing_deck_archetype_keyboard(
        self,
        participant_id: int,
        archetypes: list,
        has_more: bool = False,
        show_emoji: bool = True,
    ) -> InlineKeyboardMarkup:
        """Выбор колоды в мета-полиции с отдельными, защищаемыми callback-префиксами."""
        buttons = [
            [
                InlineKeyboardButton(
                    deck_emoji.format(name) if show_emoji else name,
                    callback_data=f"{CB_FILL_MISSING_SET}:{participant_id}:{aid}",
                )
            ]
            for aid, name in archetypes
        ]
        if has_more:
            buttons.append(
                [InlineKeyboardButton("... ещё колоды", callback_data=f"{CB_FILL_MISSING_MORE}:{participant_id}")]
            )
        buttons.append(
            [InlineKeyboardButton("Свой вариант", callback_data=f"{CB_FILL_MISSING_CUSTOM}:{participant_id}")]
        )
        return InlineKeyboardMarkup(buttons)

    def archetype_keyboard(
        self,
        tournament_id: int,
        archetypes: list,
        has_more: bool = False,
        show_emoji: bool = True,
        can_defer: bool = False,
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
        if can_defer:
            buttons.append([InlineKeyboardButton("Укажу позже", callback_data=f"{CB_DEFER_DECK}:{tournament_id}")])
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
    tournament_id: int,
    is_closed: bool = False,
    decks_hidden: bool = True,
    show_debug: bool = False,
    show_debug_meta_police: bool = False,
) -> InlineKeyboardMarkup:
    return _default.admin_more_keyboard(
        tournament_id,
        is_closed=is_closed,
        decks_hidden=decks_hidden,
        show_debug=show_debug,
        show_debug_meta_police=show_debug_meta_police,
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


def poll_broadcast_keyboard(tournament_id: int, count: int) -> InlineKeyboardMarkup:
    return _default.poll_broadcast_keyboard(tournament_id, count)


def poll_clubs_keyboard(clubs: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return _default.poll_clubs_keyboard(clubs)


def poll_club_menu_keyboard(chat_id: int, regulars_count: int) -> InlineKeyboardMarkup:
    return _default.poll_club_menu_keyboard(chat_id, regulars_count)


def poll_regulars_keyboard(
    chat_id: int,
    players: list[tuple[int, str]],
    regular_ids: set[int],
    page: int,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    return _default.poll_regulars_keyboard(chat_id, players, regular_ids, page, page_size=page_size)


def app_stats_keyboard(notify_rounds: int) -> InlineKeyboardMarkup:
    return _default.app_stats_keyboard(notify_rounds)


def app_stats_back_keyboard() -> InlineKeyboardMarkup:
    return _default.app_stats_back_keyboard()


def schedule_list_keyboard(rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return _default.schedule_list_keyboard(rows)


def schedule_row_keyboard(
    row_id: int,
    enabled: bool,
    create_time: str = "",
    game_time: str = "",
    reminder_time: str | None = None,
    imports_summary: str = "",
    weekday_ru: str = "",
) -> InlineKeyboardMarkup:
    return _default.schedule_row_keyboard(
        row_id,
        enabled,
        create_time=create_time,
        game_time=game_time,
        reminder_time=reminder_time,
        imports_summary=imports_summary,
        weekday_ru=weekday_ru,
    )


def schedule_weekday_keyboard(row_id: int, current_weekday: str) -> InlineKeyboardMarkup:
    return _default.schedule_weekday_keyboard(row_id, current_weekday)


def aetherhub_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.aetherhub_confirm_keyboard(tournament_id)


def leave_confirm_keyboard(tournament_id: int) -> InlineKeyboardMarkup:
    return _default.leave_confirm_keyboard(tournament_id)


def settings_keyboard(
    is_admin: bool = False,
    hide_deck_emoji: bool = False,
    notify_opponent_rounds: bool = False,
    notify_achievements: bool = False,
    notify_poll: bool = False,
    notify_cellar_reservations: bool | None = None,
    status_by_pairings: bool = False,
) -> InlineKeyboardMarkup:
    return _default.settings_keyboard(
        is_admin=is_admin,
        hide_deck_emoji=hide_deck_emoji,
        notify_opponent_rounds=notify_opponent_rounds,
        notify_achievements=notify_achievements,
        notify_poll=notify_poll,
        notify_cellar_reservations=notify_cellar_reservations,
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
    is_target_poll_organizer: bool = False,
    is_privileged: bool = True,
) -> InlineKeyboardMarkup:
    return _default.admin_player_actions_keyboard(
        participant_id,
        tournament_id,
        is_admin=is_admin,
        has_pairings=has_pairings,
        is_target_scorekeeper=is_target_scorekeeper,
        is_target_poll_organizer=is_target_poll_organizer,
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
    can_defer: bool = False,
) -> InlineKeyboardMarkup:
    return _default.archetype_keyboard(tournament_id, archetypes, has_more=has_more, can_defer=can_defer)
