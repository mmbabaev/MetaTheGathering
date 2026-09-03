# /settings — управление профилем пользователя — чистая бизнес-логика

from bot.handlers.base import HandlerResult
from bot.keyboards import settings_keyboard
from bot.messages import (
    ENDSTEP_USERNAME_INVALID,
    ENDSTEP_USERNAME_SAVED,
    ENDSTEP_USERNAME_TAKEN,
    INVALID_FULL_NAME,
    NAME_SAVED,
    SETTINGS_MENU,
    format_participant_name,
)
from core.config import settings as app_settings
from services.cellar import can_view_cellar_overview
from services.names import parse_full_name_input
from services.user import EndstepUsernameInvalid, EndstepUsernameTaken, UserService


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
        notify_achievements = user.notify_achievements if user else False
        notify_poll = user.notify_poll if user else False
        can_manage_cellar_notifications = can_view_cellar_overview(tg_id, user.username if user else None)
        notify_cellar_reservations = (
            user.notify_cellar_reservations if user and can_manage_cellar_notifications else None
        )
        if can_manage_cellar_notifications and user is None:
            notify_cellar_reservations = True
        status_pairings = user.status_by_pairings if user else False
        endstep_username = user.endstep_username if user and user.endstep_username else "не указан"
        text = (
            f"{SETTINGS_MENU}\n\nВаше имя: {current}\nНик Endstep: {endstep_username}\n\nВерсия: {app_settings.VERSION}"
        )
        return HandlerResult(
            text,
            keyboard=settings_keyboard(
                is_admin=self.user_svc.is_admin(tg_id),
                hide_deck_emoji=hide_emoji,
                notify_opponent_rounds=notify_rounds,
                notify_achievements=notify_achievements,
                notify_poll=notify_poll,
                notify_cellar_reservations=notify_cellar_reservations,
                status_by_pairings=status_pairings,
            ),
        )

    def handle_toggle_emoji(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_hide_deck_emoji(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_opponent_notify(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_notify_opponent_rounds(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_achievements_notify(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_notify_achievements(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_poll_notify(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_notify_poll(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_cellar_notify(self, tg_id: int) -> HandlerResult:
        user = self.user_svc.get_by_tg_id(tg_id)
        if not can_view_cellar_overview(tg_id, user.username if user else None):
            return self.handle_settings(tg_id)
        if user is None:
            self.user_svc.get_or_create(tg_id=tg_id)
        self.user_svc.toggle_notify_cellar_reservations(tg_id)
        return self.handle_settings(tg_id)

    def handle_toggle_status_by_pairings(self, tg_id: int) -> HandlerResult:
        self.user_svc.toggle_status_by_pairings(tg_id)
        return self.handle_settings(tg_id)

    def handle_settings_name_text(self, tg_id: int, name_text: str) -> HandlerResult:
        parsed = parse_full_name_input(name_text)
        if parsed is None:
            return HandlerResult(INVALID_FULL_NAME, needs_name=True)
        first_name, last_name = parsed
        self.user_svc.update_name(tg_id, first_name, last_name)
        full_name = f"{last_name} {first_name}"
        return HandlerResult(NAME_SAVED.format(full_name=full_name))

    def handle_settings_endstep_username_text(self, tg_id: int, username_text: str) -> HandlerResult:
        try:
            user = self.user_svc.update_endstep_username(tg_id, username_text)
        except EndstepUsernameInvalid:
            return HandlerResult(ENDSTEP_USERNAME_INVALID, needs_endstep_username=True)
        except EndstepUsernameTaken:
            return HandlerResult(ENDSTEP_USERNAME_TAKEN, needs_endstep_username=True)
        return HandlerResult(ENDSTEP_USERNAME_SAVED.format(username=user.endstep_username))
