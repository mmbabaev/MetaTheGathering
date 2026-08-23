from urllib.parse import urlencode

from bot.handlers.base import HandlerResult
from bot.keyboards import cellar_web_keyboard
from core.config import settings
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService
from services.web_auth import create_magic_token


class CellarHandler:
    def __init__(self, db, user_svc: UserService, feature_flags: FeatureFlagService) -> None:
        self.db = db
        self.user_svc = user_svc
        self.feature_flags = feature_flags

    def handle_open(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> HandlerResult:
        if not self.feature_flags.is_enabled(FeatureFlags.CELLAR_DECKS):
            return HandlerResult("Колоды из ячейки пока недоступны.")

        user = self.user_svc.get_or_create(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        token = create_magic_token(self.db, user)
        query = urlencode({"token": token, "next": "/cellar"})
        url = f"{settings.WEB_BASE_URL.rstrip('/')}/auth/verify?{query}"
        return HandlerResult(
            "Выберите колоду из ячейки и дату турнира:",
            keyboard=cellar_web_keyboard(url),
        )
