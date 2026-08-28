from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.telegram.features import callback_feature_toggle
from core.schemas import TournamentCreate
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.registration_message import RegistrationMessageService
from services.tournament import TournamentService


def _admin(db, user_svc):
    user = user_svc.get_or_create(tg_id=9001, username="admin")
    user.is_admin = True
    db.commit()
    return user


def _update(admin, query):
    return SimpleNamespace(effective_user=SimpleNamespace(id=admin.tg_id), callback_query=query)


async def test_toggle_on_immediately_adds_counter_to_current_message(db, user_svc):
    admin = _admin(db, user_svc)
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=100))
    RegistrationMessageService(db).upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=-1,
    )
    query = AsyncMock(data=f"feature_toggle:{FeatureFlags.LIVE_REGISTRATION_COUNT}")
    bot = AsyncMock()

    with patch("bot.telegram.features.SessionLocal", return_value=db):
        await callback_feature_toggle(_update(admin, query), SimpleNamespace(bot=bot))

    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.call_args.kwargs["text"] == "Регистрация\n\nЗаписалось: 0"


async def test_toggle_off_immediately_removes_counter_from_current_message(db, user_svc):
    admin = _admin(db, user_svc)
    FeatureFlagService(db).toggle(FeatureFlags.LIVE_REGISTRATION_COUNT)
    tournament = TournamentService(db).create_tournament(TournamentCreate(title="Pauper", chat_id=100))
    RegistrationMessageService(db).upsert_last(
        tournament_id=tournament.id,
        chat_id=100,
        message_id=10,
        base_text="Регистрация",
        button_url=None,
        participant_count=0,
    )
    query = AsyncMock(data=f"feature_toggle:{FeatureFlags.LIVE_REGISTRATION_COUNT}")
    bot = AsyncMock()

    with patch("bot.telegram.features.SessionLocal", return_value=db):
        await callback_feature_toggle(_update(admin, query), SimpleNamespace(bot=bot))

    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.call_args.kwargs["text"] == "Регистрация"


async def test_toggle_on_cellar_immediately_syncs_sheet_catalog(db, user_svc):
    admin = _admin(db, user_svc)
    query = AsyncMock(data=f"feature_toggle:{FeatureFlags.CELLAR_DECKS}")
    sync = AsyncMock(return_value=(38, 0, 0))

    with (
        patch("bot.telegram.features.SessionLocal", return_value=db),
        patch("bot.telegram.features.CellarCatalogSyncJob") as job_class,
    ):
        job_class.return_value.run = sync
        await callback_feature_toggle(_update(admin, query), SimpleNamespace(bot=AsyncMock()))

    sync.assert_awaited_once_with(db=db)
