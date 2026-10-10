from datetime import timedelta

import pytest

from core import models
from core.models import utc_now
from services.web_auth import (
    complete_telegram_auth_attempt,
    consume_telegram_auth_attempt,
    create_telegram_auth_attempt,
    telegram_auth_attempt_status,
)
from web.routes.auth import telegram_login_complete, telegram_login_status


def test_telegram_auth_attempt_is_pending_until_bot_completes(db, user_svc):
    token = create_telegram_auth_attempt(db)
    assert telegram_auth_attempt_status(db, token) == ("pending", None)

    user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    assert complete_telegram_auth_attempt(db, token, user) is True

    status, authenticated_user = telegram_auth_attempt_status(db, token)
    assert status == "complete"
    assert authenticated_user.id == user.id


def test_telegram_auth_attempt_cannot_be_replayed(db, user_svc):
    token = create_telegram_auth_attempt(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    bob = user_svc.get_or_create(tg_id=1002, first_name="Bob")

    assert complete_telegram_auth_attempt(db, token, alice) is True
    assert complete_telegram_auth_attempt(db, token, bob) is False
    assert consume_telegram_auth_attempt(db, token).id == alice.id
    assert consume_telegram_auth_attempt(db, token) is None


def test_telegram_auth_attempt_expires(db, user_svc):
    token = create_telegram_auth_attempt(db)
    record = db.query(models.WebTelegramAuthAttempt).one()
    record.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()

    user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    assert telegram_auth_attempt_status(db, token) == ("expired", None)
    assert complete_telegram_auth_attempt(db, token, user) is False


@pytest.mark.asyncio
async def test_telegram_login_routes_poll_then_issue_one_session(db, user_svc):
    token = create_telegram_auth_attempt(db)
    assert await telegram_login_status(token, "/dashboard", db) == {"status": "pending"}

    user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    assert complete_telegram_auth_attempt(db, token, user) is True

    assert await telegram_login_status(token, "//evil.example", db) == {
        "status": "authenticated",
        "redirect": "/",
    }
    response = await telegram_login_complete(token, "/dashboard", db)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert "web_session=" in response.headers["set-cookie"]
    replay = await telegram_login_complete(token, "/dashboard", db)
    assert replay.status_code == 303
