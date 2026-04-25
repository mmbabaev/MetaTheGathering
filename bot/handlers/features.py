from bot.handlers.base import HandlerResult
from bot.keyboards import features_keyboard
from bot.messages import NOT_ADMIN
from services.feature_flags import FeatureFlagService
from services.user import UserService


class FeaturesHandler:
    def __init__(self, user_svc: UserService, ff_svc: FeatureFlagService) -> None:
        self.user_svc = user_svc
        self.ff_svc = ff_svc

    def handle_features_list(self, tg_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        flags = self.ff_svc.list_flags()
        return HandlerResult("⚙️ Feature flags:", keyboard=features_keyboard(flags))

    def handle_toggle_flag(self, tg_id: int, flag_name: str) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        try:
            self.ff_svc.toggle(flag_name)
        except ValueError as e:
            return HandlerResult(str(e), is_alert=True)
        flags = self.ff_svc.list_flags()
        return HandlerResult("⚙️ Feature flags:", keyboard=features_keyboard(flags))
