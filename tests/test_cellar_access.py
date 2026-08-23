from urllib.parse import parse_qs, urlparse

import pytest

from bot.handlers.cellar import CellarHandler
from core.config import settings
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.user import UserService
from services.web_auth import verify_magic_token
from web.routes.auth import auth_verify


def _handler(db):
    return CellarHandler(db, UserService(db), FeatureFlagService(db))


def test_cellar_command_is_disabled_by_default(db):
    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
    )

    assert "недоступны" in result.text
    assert result.keyboard is None
    assert UserService(db).get_by_tg_id(1001) is None


def test_cellar_command_creates_personal_one_time_web_link(db, monkeypatch):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    monkeypatch.setattr(settings, "WEB_BASE_URL", "https://debug.example.test")

    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
    )

    url = result.keyboard.inline_keyboard[0][0].url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "debug.example.test"
    assert parsed.path == "/auth/verify"
    assert query["next"] == ["/cellar"]
    user = verify_magic_token(db, query["token"][0])
    assert user is not None
    assert user.tg_id == 1001
    assert verify_magic_token(db, query["token"][0]) is None


@pytest.mark.asyncio
async def test_telegram_magic_link_redirects_to_cellar(db):
    FeatureFlagService(db).toggle(FeatureFlags.CELLAR_DECKS)
    result = _handler(db).handle_open(
        tg_id=1001,
        username="alice",
        first_name="Alice",
        last_name=None,
    )
    token = parse_qs(urlparse(result.keyboard.inline_keyboard[0][0].url).query)["token"][0]

    response = await auth_verify(None, token, "/cellar", db)

    assert response.status_code == 303
    assert response.headers["location"] == "/cellar"
