"""Хендлер статистики приложения — только для владельца (issue: /app_statistics)."""

from bot.handlers.base import HandlerResult
from bot.keyboards import Keyboards
from core.config import settings
from services.app_stats import AppStatsService

NOT_OWNER = "Эта команда доступна только владельцу бота."


def _user_line(user) -> str:
    parts = []
    if user.username:
        parts.append(f"@{user.username}")
    name = " ".join(filter(None, [user.first_name, user.last_name]))
    if name:
        parts.append(name)
    return " ".join(parts) if parts else f"id{user.tg_id}"


class AppStatsHandler:
    def __init__(self, stats_svc: AppStatsService, keyboards: Keyboards) -> None:
        self.stats_svc = stats_svc
        self.keyboards = keyboards

    def _is_owner(self, tg_id: int) -> bool:
        return settings.OWNER_CHAT_ID is not None and tg_id == settings.OWNER_CHAT_ID

    def handle_home(self, tg_id: int) -> HandlerResult:
        """Меню статистики приложения."""
        if not self._is_owner(tg_id):
            return HandlerResult(NOT_OWNER)
        notify_rounds = self.stats_svc.notify_rounds_count()
        text = "📊 Статистика приложения"
        return HandlerResult(text, keyboard=self.keyboards.app_stats_keyboard(notify_rounds=notify_rounds))

    def handle_notify_rounds_list(self, tg_id: int) -> HandlerResult:
        """Список игроков, включивших уведомления о раундах."""
        if not self._is_owner(tg_id):
            return HandlerResult(NOT_OWNER, is_alert=True)
        users = self.stats_svc.notify_rounds_users()
        lines = [f"🔔 Уведомления о раундах — включили {len(users)}:"]
        lines += [f"  • {_user_line(u)}" for u in users] or ["  (пока никто)"]
        return HandlerResult("\n".join(lines), keyboard=self.keyboards.app_stats_back_keyboard())
