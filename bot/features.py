from services.feature_flags import FeatureFlags, FeatureFlagService


class FeatureService:
    def __init__(self, ff_svc: FeatureFlagService) -> None:
        self._ff_svc = ff_svc

    def can_fill_opponent_decks(self) -> bool:
        return self._ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS)

    def is_payment_enabled(self) -> bool:
        return self._ff_svc.is_enabled(FeatureFlags.PAYMENT)
