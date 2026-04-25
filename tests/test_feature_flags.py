import pytest

from bot.handlers.features import FeaturesHandler
from bot.keyboards import features_keyboard
from bot.messages import NOT_ADMIN
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService


@pytest.fixture
def ff_svc(db):
    return FeatureFlagService(db)


@pytest.fixture
def admin_user(user_svc, db):
    user = user_svc.get_or_create(tg_id=9001, username="admin")
    user.is_admin = True
    db.commit()
    return user


@pytest.fixture
def handler(db, user_svc, ff_svc):
    return FeaturesHandler(user_svc, ff_svc)


# ── FeatureFlagService ────────────────────────────────────────────────────────


class TestFeatureFlagService:
    def test_is_enabled_returns_default_when_no_row(self, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS) is True

    def test_ensure_defaults_creates_rows(self, ff_svc, db):
        ff_svc.ensure_defaults()
        flags = ff_svc.list_flags()
        assert len(flags) == len(ff_svc.KNOWN_FLAGS if hasattr(ff_svc, "KNOWN_FLAGS") else [flags])
        assert any(f.name == FeatureFlags.RECORD_OPPONENTS for f in flags)

    def test_list_flags_enabled_by_default(self, ff_svc):
        flags = ff_svc.list_flags()
        record = next(f for f in flags if f.name == FeatureFlags.RECORD_OPPONENTS)
        assert record.enabled is True

    def test_toggle_disables_flag(self, ff_svc):
        result = ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        assert result is False
        assert ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS) is False

    def test_toggle_twice_restores_flag(self, ff_svc):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        result = ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        assert result is True
        assert ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS) is True

    def test_toggle_unknown_flag_raises(self, ff_svc):
        with pytest.raises(ValueError, match="Unknown feature flag"):
            ff_svc.toggle("nonExistentFlag")

    def test_list_flags_reflects_toggle(self, ff_svc):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        flags = ff_svc.list_flags()
        record = next(f for f in flags if f.name == FeatureFlags.RECORD_OPPONENTS)
        assert record.enabled is False


# ── FeaturesHandler ───────────────────────────────────────────────────────────


class TestFeaturesHandler:
    def test_non_admin_gets_denied(self, handler, user_svc):
        user = user_svc.get_or_create(tg_id=42, username="player")
        result = handler.handle_features_list(user.tg_id)
        assert result.text == NOT_ADMIN
        assert result.keyboard is None

    def test_admin_gets_flag_list(self, handler, admin_user):
        result = handler.handle_features_list(admin_user.tg_id)
        assert result.keyboard is not None
        assert "Feature flags" in result.text

    def test_toggle_denied_for_non_admin(self, handler, user_svc):
        user = user_svc.get_or_create(tg_id=43, username="player2")
        result = handler.handle_toggle_flag(user.tg_id, FeatureFlags.RECORD_OPPONENTS)
        assert result.is_alert is True
        assert result.text == NOT_ADMIN

    def test_toggle_switches_flag(self, handler, admin_user, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS) is True
        result = handler.handle_toggle_flag(admin_user.tg_id, FeatureFlags.RECORD_OPPONENTS)
        assert result.keyboard is not None
        assert ff_svc.is_enabled(FeatureFlags.RECORD_OPPONENTS) is False

    def test_toggle_unknown_flag_returns_alert(self, handler, admin_user):
        result = handler.handle_toggle_flag(admin_user.tg_id, "ghostFlag")
        assert result.is_alert is True


# ── features_keyboard ─────────────────────────────────────────────────────────


class TestFeaturesKeyboard:
    def test_enabled_flag_shows_checkmark(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        buttons = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any(b.startswith("✅") for b in buttons)

    def test_disabled_flag_shows_cross(self, ff_svc):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        buttons = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any(b.startswith("❌") for b in buttons)

    def test_callback_data_contains_flag_name(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any(FeatureFlags.RECORD_OPPONENTS in cb for cb in callbacks)
