# /settings — управление профилем пользователя — чистая бизнес-логика

from services.user import UserService
from bot.handlers.base import HandlerResult
from bot.keyboards import settings_keyboard
from bot.messages import SETTINGS_MENU, NAME_SAVED


class SettingsHandler:
    def __init__(self, user_svc: UserService) -> None:
        self.user_svc = user_svc

    def handle_settings(self, tg_id: int) -> HandlerResult:
        """Показывает меню настроек с кнопкой смены имени."""
        user = self.user_svc.get_by_tg_id(tg_id)
        name_parts = []
        if user and user.first_name:
            name_parts.append(user.first_name)
        if user and user.last_name:
            name_parts.append(user.last_name)
        current = " ".join(name_parts) if name_parts else "не указано"
        text = f"{SETTINGS_MENU}\n\nВаше имя: {current}"
        return HandlerResult(text, keyboard=settings_keyboard())

    def handle_settings_name_text(self, tg_id: int, name_text: str) -> HandlerResult:
        """Сохраняет новое имя пользователя."""
        parts = name_text.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        self.user_svc.update_name(tg_id, first_name, last_name)
        full_name = f"{first_name} {last_name}" if last_name else first_name
        return HandlerResult(NAME_SAVED.format(full_name=full_name))
