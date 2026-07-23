"""Хендлеры расписания клубов — чистая логика без Telegram (issue #124/#125)."""

from bot.handlers.base import HandlerResult
from bot.keyboards import Keyboards
from bot.messages import NOT_ADMIN, format_schedule_rows, schedule_row_label
from core.config import settings
from services.schedule import WEEKDAY_RU, ScheduleService, parse_import_times
from services.user import UserService

SCHEDULE_ROW_NOT_FOUND = "Строка расписания не найдена."


class ScheduleHandler:
    def __init__(self, schedule_svc: ScheduleService, user_svc: UserService, keyboards: Keyboards) -> None:
        self.schedule_svc = schedule_svc
        self.user_svc = user_svc
        self.keyboards = keyboards

    def handle_schedule_list(self, tg_id: int) -> HandlerResult:
        """`/schedule` — текст расписания + кнопка на каждую строку."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        rows = self.schedule_svc.list_rows()
        text = format_schedule_rows(rows, settings.TOURNAMENT_TIMEZONE)
        if not rows:
            return HandlerResult(text)
        buttons = [(r.id, schedule_row_label(r)) for r in rows]
        return HandlerResult(text, keyboard=self.keyboards.schedule_list_keyboard(buttons))

    def handle_schedule_row(self, tg_id: int, row_id: int) -> HandlerResult:
        """Карточка одной строки расписания."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        row = self.schedule_svc.get_row(row_id)
        if row is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        return HandlerResult(_row_card_text(row), keyboard=self.keyboards.schedule_row_keyboard(row.id, row.enabled))

    def handle_toggle_row(self, tg_id: int, row_id: int) -> HandlerResult:
        """Включает/выключает строку и возвращает обновлённую карточку."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        new_state = self.schedule_svc.toggle_enabled(row_id)
        if new_state is None:
            return HandlerResult(SCHEDULE_ROW_NOT_FOUND, is_alert=True)
        row = self.schedule_svc.get_row(row_id)
        return HandlerResult(_row_card_text(row), keyboard=self.keyboards.schedule_row_keyboard(row.id, row.enabled))


def _row_card_text(row) -> str:
    day = WEEKDAY_RU.get(row.weekday, row.weekday)
    status = "✅ включено" if row.enabled else "⏸ выключено"
    lines = [
        f"📅 {row.club_name} · {day} — {status}",
        "",
        f"🕐 Создание турнира: {row.create_time}",
        f"🎮 Время игры: {row.game_time}",
        f"🔔 Напоминание: {row.reminder_time or 'выключено'}",
    ]
    times = parse_import_times(row.import_times)
    lines.append(f"🔄 Импорты: {', '.join(times) if times else 'выключены'}")
    if not row.enabled:
        lines += ["", "Пока выключено — турнир в этот день не создаётся, напоминание и импорты не идут."]
    return "\n".join(lines)
