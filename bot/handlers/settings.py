# /settings — управление профилем пользователя — чистая бизнес-логика

from bot.handlers.base import HandlerResult
from bot.keyboards import settings_keyboard
from bot.messages import NAME_SAVED, SETTINGS_MENU, format_participant_name
from core.config import settings as app_settings
from services.user import UserService


class SettingsHandler:
    def __init__(self, user_svc: UserService) -> None:
        self.user_svc = user_svc

    def handle_settings(self, tg_id: int) -> HandlerResult:
        user = self.user_svc.get_by_tg_id(tg_id)
        current = (
            format_participant_name(user.first_name if user else None, user.last_name if user else None) or "не указано"
        )
        hide_emoji = user.hide_deck_emoji if user else False
        notify_rounds = user.notify_opponent_rounds if user else False
        text = f"{SETTINGS_MENU}\n\nВаше имя: {current}\n\nВерсия: {app_settings.VERSION}"
        return HandlerResult(
            text,
            keyboard=settings_keyboard(
                is_admin=self.user_svc.is_admin(tg_id),
                hide_deck_emoji=hide_emoji,
                notify_opponent_rounds=notify_rounds,
            ),
        )

    def handle_toggle_emoji(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_hide_deck_emoji(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_opponent_notify(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_notify_opponent_rounds(tg_id)
        return self.handle_settings(tg_id)

    def handle_settings_name_text(self, tg_id: int, name_text: str) -> HandlerResult:
        parts = name_text.strip().split(None, 1)
        # Input format: "Фамилия Имя" — first word is last_name, second is first_name
        last_name = parts[0]
        first_name = parts[1] if len(parts) > 1 else None
        self.user_svc.update_name(tg_id, first_name or last_name, last_name if first_name else None)
        full_name = f"{last_name} {first_name}" if first_name else last_name
        return HandlerResult(NAME_SAVED.format(full_name=full_name))
