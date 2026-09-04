"""Хендлеры расписания клубов — чистая логика без Telegram (issue #124/#125)."""

from bot.handlers.base import HandlerResult
from bot.keyboards import Keyboards
from bot.messages import NOT_ADMIN, format_schedule_rows, schedule_row_label
from core.clubs import club_identities
from core.config import settings
from services.schedule import (
    EDITABLE_TIME_FIELDS,
    WEEKDAY_RU,
    WEEKDAYS,
    ScheduleService,
    generate_import_times,
    normalize_time,
    parse_import_times,
)
from services.user import UserService

SCHEDULE_ROW_NOT_FOUND = "Строка расписания не найдена."
CLUB_SETTINGS_NOT_FOUND = "Настройки клуба не найдены."
BAD_TIME = "❌ Неверный формат. Пришли время как ЧЧ:ММ (например 12:30)."
BAD_IMPORTS = "❌ Неверный формат. Пришли начало-конец/шаг, например 20:00-00:30/30, или «выкл»."
WEEKDAY_TAKEN = "⚠️ У этого клуба уже есть расписание на этот день."

_DISABLE_WORDS = {"выкл", "выключить", "-", "нет", "off"}

_TIME_PROMPTS = {
    "create": "Пришли время создания турнира в формате ЧЧ:ММ (например 12:00).",
    "game": "Пришли время игры в формате ЧЧ:ММ (например 19:30).",
    "reminder": "Пришли время напоминания ЧЧ:ММ (например 19:25), или «выкл» чтобы отключить.",
}
IMPORTS_PROMPT = (
    "Пришли расписание импортов с AetherHub: начало-конец/шаг_в_минутах.\n"
    "Например 20:00-00:30/30 — каждые 30 минут с 20:00 до 00:30.\n"
    "Или «выкл» чтобы отключить импорты."
)


def imports_summary(times: list[str]) -> str:
    if not times:
        return "выключены"
    if len(times) == 1:
        return times[0]
    return f"{times[0]}–{times[-1]} ({len(times)})"


class ScheduleHandler:
    def __init__(self, schedule_svc: ScheduleService, user_svc: UserService, keyboards: Keyboards) -> None:
        self.schedule_svc = schedule_svc
        self.user_svc = user_svc
        self.keyboards = keyboards

    # --- список ---

    def handle_schedule_list(self, tg_id: int) -> HandlerResult:
        """`/schedule` — текст расписания + кнопка на каждую строку."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        rows = self.schedule_svc.list_rows()
        text = format_schedule_rows(rows, settings.TOURNAMENT_TIMEZONE)
        buttons = [(r.id, schedule_row_label(r)) for r in rows]
        return HandlerResult(text, keyboard=self.keyboards.schedule_list_keyboard(buttons))

    def handle_club_settings_list(self, tg_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        self.schedule_svc.ensure_club_settings()
        rows = self.schedule_svc.list_club_settings()
        prefixes = {identity.name: identity.title_prefix for identity in club_identities()}
        buttons = [
            (
                row.id,
                f"{prefixes.get(row.club_name, '')}{row.club_name} · "
                f"паринги {'вкл' if row.publish_pairings else 'выкл'}",
            )
            for row in rows
        ]
        return HandlerResult(
            "⚙️ Настройки клубов\n\nПубликация парингов в чат по умолчанию выключена.",
            keyboard=self.keyboards.club_pairing_settings_list_keyboard(buttons),
        )

    def handle_club_settings(self, tg_id: int, settings_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        row = self.schedule_svc.get_club_settings(settings_id)
        if row is None:
            return HandlerResult(CLUB_SETTINGS_NOT_FOUND, is_alert=True)
        state = "включена" if row.publish_pairings else "выключена"
        return HandlerResult(
            f"⚙️ {row.club_name}\n\nПубликация новых парингов в чат: {state}.",
            keyboard=self.keyboards.club_pairing_settings_keyboard(row.id, row.publish_pairings),
        )

    def handle_toggle_pairings_publication(self, tg_id: int, settings_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if self.schedule_svc.toggle_pairings_publication(settings_id) is None:
            return HandlerResult(CLUB_SETTINGS_NOT_FOUND, is_alert=True)
        return self.handle_club_settings(tg_id, settings_id)

    # --- карточка строки ---

    def handle_schedule_row(self, tg_id: int, row_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        row = self.schedule_svc.get_row(row_id)
        if row is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        return self._card_result(row)

    def handle_toggle_row(self, tg_id: int, row_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        new_state = self.schedule_svc.toggle_enabled(row_id)
        if new_state is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        return self._card_result(self.schedule_svc.get_row(row_id))

    # --- правка времён (текстовый ввод) ---

    def field_name(self, field_idx: int) -> str | None:
        """Индекс кнопки → имя поля времени, или None если вне диапазона."""
        if 0 <= field_idx < len(EDITABLE_TIME_FIELDS):
            return EDITABLE_TIME_FIELDS[field_idx]
        return None

    def handle_edit_field_prompt(self, tg_id: int, row_id: int, field: str) -> HandlerResult:
        """Проверяет права/строку и возвращает текст-подсказку для ввода времени."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if self.schedule_svc.get_row(row_id) is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        return HandlerResult(_TIME_PROMPTS[field])

    def handle_set_time(self, tg_id: int, row_id: int, field: str, text: str) -> HandlerResult:
        """Применяет введённое время. field: create/game/reminder."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if self.schedule_svc.get_row(row_id) is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)

        if field == "reminder" and text.strip().lower() in _DISABLE_WORDS:
            self.schedule_svc.set_reminder(row_id, None)
            return self._card_result(self.schedule_svc.get_row(row_id))

        value = normalize_time(text)
        if value is None:
            return HandlerResult(BAD_TIME)
        if field == "reminder":
            self.schedule_svc.set_reminder(row_id, value)
        else:
            self.schedule_svc.set_time_field(row_id, field, value)
        return self._card_result(self.schedule_svc.get_row(row_id))

    def handle_imports_prompt(self, tg_id: int, row_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if self.schedule_svc.get_row(row_id) is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        return HandlerResult(IMPORTS_PROMPT)

    def handle_set_imports(self, tg_id: int, row_id: int, text: str) -> HandlerResult:
        """Применяет пресет импортов «начало-конец/шаг» или отключает импорты."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if self.schedule_svc.get_row(row_id) is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)

        if text.strip().lower() in _DISABLE_WORDS:
            self.schedule_svc.set_import_times(row_id, [])
            return self._card_result(self.schedule_svc.get_row(row_id))

        times = _parse_imports_preset(text)
        if times is None:
            return HandlerResult(BAD_IMPORTS)
        self.schedule_svc.set_import_times(row_id, times)
        return self._card_result(self.schedule_svc.get_row(row_id))

    # --- день недели ---

    def handle_weekday_picker(self, tg_id: int, row_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        row = self.schedule_svc.get_row(row_id)
        if row is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        text = f"📆 {row.club_name}: выбери день недели"
        return HandlerResult(text, keyboard=self.keyboards.schedule_weekday_keyboard(row_id, row.weekday))

    def handle_set_weekday(self, tg_id: int, row_id: int, weekday_idx: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if not (0 <= weekday_idx < len(WEEKDAYS)):
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        outcome = self.schedule_svc.set_weekday(row_id, WEEKDAYS[weekday_idx])
        if outcome == "not_found":
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        if outcome == "duplicate":
            return HandlerResult(WEEKDAY_TAKEN, is_alert=True)
        return self._card_result(self.schedule_svc.get_row(row_id))

    # --- общий рендер карточки ---

    def _card_result(self, row) -> HandlerResult:
        keyboard = self.keyboards.schedule_row_keyboard(
            row.id,
            row.enabled,
            create_time=row.create_time,
            game_time=row.game_time,
            reminder_time=row.reminder_time,
            imports_summary=imports_summary(parse_import_times(row.import_times)),
            weekday_ru=WEEKDAY_RU.get(row.weekday, row.weekday),
        )
        return HandlerResult(_row_card_text(row), keyboard=keyboard)


def _parse_imports_preset(text: str) -> list[str] | None:
    """«20:00-00:30/30» → список времён. None если формат/значения не валидны."""
    text = text.strip().replace(" ", "")
    if "/" not in text or "-" not in text:
        return None
    window, _, step_str = text.partition("/")
    start_str, _, end_str = window.partition("-")
    start = normalize_time(start_str)
    end = normalize_time(end_str)
    if start is None or end is None or not step_str.isdigit():
        return None
    return generate_import_times(start, end, int(step_str))


def _row_card_text(row) -> str:
    day = WEEKDAY_RU.get(row.weekday, row.weekday)
    status = "✅ включено" if row.enabled else "⏸ выключено"
    times = parse_import_times(row.import_times)
    days_before = getattr(row, "create_days_before", 0)
    create_day = "накануне в " if days_before == 1 else (f"за {days_before} дн. в " if days_before else "")
    lines = [
        f"📅 {row.club_name} · {day} — {status}",
        "",
        f"🕐 Создание турнира: {create_day}{row.create_time}",
        f"🎮 Время игры: {row.game_time}",
        f"🔔 Напоминание: {row.reminder_time or 'выключено'}",
        f"🔄 Импорты: {', '.join(times) if times else 'выключены'}",
    ]
    if not row.enabled:
        lines += ["", "Пока выключено — турнир в этот день не создаётся, напоминание и импорты не идут."]
    return "\n".join(lines)
