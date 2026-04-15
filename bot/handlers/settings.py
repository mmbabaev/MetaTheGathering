# /settings — управление профилем пользователя — чистая бизнес-логика

from core.config import settings as app_settings
from core.pretend import is_pretending, toggle_pretend
from services.user import UserService
from bot.handlers.base import HandlerResult
from bot.keyboards import settings_keyboard
from bot.messages import SETTINGS_MENU, NAME_SAVED


class SettingsHandler:
    def __init__(self, user_svc: UserService) -> None:
        self.user_svc = user_svc

    def _is_real_admin(self, tg_id: int) -> bool:
        """Проверяет реальные права админа (без учёта pretend-режима)."""
        if tg_id in app_settings.admin_ids:
            return True
        user = self.user_svc.get_by_tg_id(tg_id)
        return user is not None and (user.is_admin or user.is_superadmin)

    def handle_settings(self, tg_id: int) -> HandlerResult:
        """Показывает меню настроек с кнопкой смены имени."""
        user = self.user_svc.get_by_tg_id(tg_id)
        name_parts = []
        if user and user.first_name:
            name_parts.append(user.first_name)
        if user and user.last_name:
            name_parts.append(user.last_name)
        current = " ".join(name_parts) if name_parts else "не указано"

        pretending = is_pretending(tg_id)
        real_admin = self._is_real_admin(tg_id)

        mode_note = "\n\n🎭 Режим: притворяешься пользователем" if pretending else ""
        text = f"{SETTINGS_MENU}\n\nВаше имя: {current}{mode_note}"
        return HandlerResult(
            text,
            keyboard=settings_keyboard(is_admin=real_admin, is_pretending=pretending),
        )

    def handle_toggle_pretend(self, tg_id: int) -> HandlerResult:
        """Переключает режим претворения. Доступно только реальным админам."""
        if not self._is_real_admin(tg_id):
            return HandlerResult("Только для администраторов.", is_alert=True)
        new_state = toggle_pretend(tg_id)
        if new_state:
            text = "🎭 Включён режим пользователя. Теперь ты видишь бота как обычный игрок.\n\nОткрой /settings чтобы вернуться в режим админа."
        else:
            text = "🔑 Режим администратора восстановлен."
        return HandlerResult(text)

    def handle_settings_name_text(self, tg_id: int, name_text: str) -> HandlerResult:
        """Сохраняет новое имя пользователя."""
        parts = name_text.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        self.user_svc.update_name(tg_id, first_name, last_name)
        full_name = f"{first_name} {last_name}" if last_name else first_name
        return HandlerResult(NAME_SAVED.format(full_name=full_name))
