import pytest

from bot.handlers.features import FeaturesHandler
from bot.keyboards import features_keyboard
from bot.messages import NOT_ADMIN
from core import models
from services.feature_flags import KNOWN_FLAGS, FeatureFlags, FeatureFlagService
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
        assert len(flags) == len(KNOWN_FLAGS)
        assert any(f.name == FeatureFlags.RECORD_OPPONENTS for f in flags)

    def test_list_flags_enabled_by_default(self, ff_svc):
        flags = ff_svc.list_flags()
        record = next(f for f in flags if f.name == FeatureFlags.RECORD_OPPONENTS)
        assert record.enabled is True

    def test_magicoculus_import_is_enabled_by_default(self, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.MAGIC_OCULUS_IMPORT) is True

    def test_live_registration_count_is_disabled_by_default(self, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.LIVE_REGISTRATION_COUNT) is False

    def test_cellar_decks_is_disabled_by_default(self, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.CELLAR_DECKS) is False

    def test_owner_board_lab_is_enabled_by_default(self, ff_svc):
        assert ff_svc.is_enabled(FeatureFlags.ACHIEVEMENT_BOARD_LAB) is True

    def test_ensure_defaults_updates_stale_metadata_but_preserves_override(self, ff_svc, db):
        db.add(
            models.FeatureFlag(
                name=FeatureFlags.MAGIC_OCULUS_IMPORT,
                description="old",
                value_type="old",
                default_value="false",
                current_value="false",
            )
        )
        db.commit()

        ff_svc.ensure_defaults()

        row = db.query(models.FeatureFlag).filter_by(name=FeatureFlags.MAGIC_OCULUS_IMPORT).one()
        assert row.description == KNOWN_FLAGS[FeatureFlags.MAGIC_OCULUS_IMPORT].description
        assert row.value_type == "bool"
        assert row.default_value == "true"
        assert row.current_value == "false"

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
    def test_each_flag_has_two_buttons(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        for row in kb.inline_keyboard:
            assert len(row) == 2

    def test_enabled_flag_toggle_shows_checkmark(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        toggle_buttons = [row[1].text for row in kb.inline_keyboard]
        assert any(b == "✅" for b in toggle_buttons)

    def test_disabled_flag_toggle_shows_cross(self, ff_svc):
        ff_svc.toggle(FeatureFlags.RECORD_OPPONENTS)
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        toggle_buttons = [row[1].text for row in kb.inline_keyboard]
        assert any(b == "❌" for b in toggle_buttons)

    def test_info_button_callback_contains_flag_name(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        info_callbacks = [row[0].callback_data for row in kb.inline_keyboard]
        assert any(FeatureFlags.RECORD_OPPONENTS in cb for cb in info_callbacks)

    def test_toggle_button_callback_contains_flag_name(self, ff_svc):
        flags = ff_svc.list_flags()
        kb = features_keyboard(flags)
        toggle_callbacks = [row[1].callback_data for row in kb.inline_keyboard]
        assert any(FeatureFlags.RECORD_OPPONENTS in cb for cb in toggle_callbacks)
