"""Admin UI for per-club manual-announcement destinations."""

from bot.handlers.base import HandlerResult
from bot.keyboards import Keyboards
from bot.messages import NOT_ADMIN
from core.clubs import ClubIdentity, club_identities
from services.club_settings import (
    ClubAnnouncementSettingsService,
    InvalidClubAnnouncementSetting,
)
from services.user import UserService


class ClubSettingsHandler:
    def __init__(
        self,
        settings: ClubAnnouncementSettingsService,
        users: UserService,
        keyboards: Keyboards,
    ) -> None:
        self.settings = settings
        self.users = users
        self.keyboards = keyboards

    def handle_list(self, tg_id: int) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        clubs = club_identities()
        buttons = [
            (index, f"{identity.title_prefix}{identity.name} · {self.settings.current_target(identity).label}")
            for index, identity in enumerate(clubs)
        ]
        return HandlerResult(
            "⚙️ Чаты клубов\n\nВыберите клуб. Настройка действует на новые ручные турниры:",
            keyboard=self.keyboards.club_settings_list_keyboard(buttons),
        )

    def handle_club(self, tg_id: int, club_index: int) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        identity = self._identity(club_index)
        if identity is None:
            return HandlerResult("Клуб не найден.", is_alert=True)
        return self._card(identity, club_index)

    def handle_set_destination(self, tg_id: int, club_index: int, destination: str) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        identity = self._identity(club_index)
        if identity is None:
            return HandlerResult("Клуб не найден.", is_alert=True)
        try:
            self.settings.set_destination(identity.name, destination)
        except InvalidClubAnnouncementSetting as exc:
            return HandlerResult(str(exc), is_alert=True)
        return self._card(identity, club_index, saved=True)

    def _card(self, identity: ClubIdentity, club_index: int, *, saved: bool = False) -> HandlerResult:
        target = self.settings.current_target(identity)
        suffix = "\n\n✅ Сохранено." if saved else ""
        return HandlerResult(
            f"⚙️ {identity.title_prefix}{identity.name}\n\n"
            f"Чат для новых ручных турниров: {target.label}\n\n"
            "Выберите, куда отправлять объявление. Уже запланированные турниры не изменятся."
            f"{suffix}",
            keyboard=self.keyboards.club_settings_chat_keyboard(
                club_index,
                target.destination,
                real_chat_label=identity.real_chat_label,
            ),
        )

    @staticmethod
    def _identity(club_index: int) -> ClubIdentity | None:
        identities = club_identities()
        return identities[club_index] if 0 <= club_index < len(identities) else None
