from services.feature_flags import FeatureFlags, FeatureFlagService


class FeatureService:
    def __init__(self, ff_svc: FeatureFlagService) -> None:
        self._ff_svc = ff_svc

    def can_fill_opponent_decks(self) -> bool:
        return self._ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS)

    def is_payment_enabled(self) -> bool:
        return self._ff_svc.is_enabled(FeatureFlags.PAYMENT)

    def are_achievements_enabled(self) -> bool:
        """Движок ачивок считает и пишет в БД (в теневом режиме — тоже True)."""
        return self._ff_svc.is_enabled(FeatureFlags.ACHIEVEMENTS)

    def is_achievements_ui_public(self) -> bool:
        """/achievements доступна всем игрокам, а не только владельцу и админам."""
        return self._ff_svc.is_enabled(FeatureFlags.ACHIEVEMENTS_PUBLIC_UI)

    def are_achievement_dms_enabled(self) -> bool:
        """Уведомления уходят самим игрокам. Пока выключено — получатель только владелец."""
        return self._ff_svc.is_enabled(FeatureFlags.ACHIEVEMENTS_PLAYER_DM)
