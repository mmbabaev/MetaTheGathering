"""One-time web authentication tokens shared by Telegram and web entry points."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

MAGIC_LINK_TTL_MINUTES = 15
TELEGRAM_LOGIN_TTL_MINUTES = 5


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_magic_token(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
    db.add(models.WebAuthToken(user_id=user.id, token_hash=_hash_token(token), expires_at=expires_at))
    db.commit()
    return token


def verify_magic_token(db: Session, token: str) -> models.User | None:
    token_hash = _hash_token(token)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = db.execute(
        select(models.WebAuthToken).where(
            models.WebAuthToken.token_hash == token_hash,
            models.WebAuthToken.expires_at > now,
            models.WebAuthToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    record.used_at = now
    db.commit()
    return record.user


def create_telegram_auth_attempt(db: Session) -> str:
    """Create an opaque, short-lived token used by the Telegram deep link."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=TELEGRAM_LOGIN_TTL_MINUTES)
    db.add(
        models.WebTelegramAuthAttempt(
            token_hash=_hash_token(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return token


def complete_telegram_auth_attempt(db: Session, token: str, user: models.User) -> bool:
    """Complete an attempt exactly once for the Telegram user who opened the link."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = db.execute(
        select(models.WebTelegramAuthAttempt).where(
            models.WebTelegramAuthAttempt.token_hash == _hash_token(token),
            models.WebTelegramAuthAttempt.expires_at > now,
            models.WebTelegramAuthAttempt.completed_at.is_(None),
        )
    ).scalar_one_or_none()
    if record is None:
        return False
    record.user_id = user.id
    record.completed_at = now
    db.commit()
    return True


def telegram_auth_attempt_status(db: Session, token: str) -> tuple[str, models.User | None]:
    """Return ``pending``, ``complete`` or ``expired`` without revealing token data."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = db.execute(
        select(models.WebTelegramAuthAttempt).where(
            models.WebTelegramAuthAttempt.token_hash == _hash_token(token),
        )
    ).scalar_one_or_none()
    if record is None or record.expires_at <= now or record.consumed_at is not None:
        return "expired", None
    if record.completed_at is None or record.user_id is None:
        return "pending", None
    return "complete", record.user


def consume_telegram_auth_attempt(db: Session, token: str) -> models.User | None:
    """Consume a completed browser login token and return its user once."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = db.execute(
        select(models.WebTelegramAuthAttempt).where(
            models.WebTelegramAuthAttempt.token_hash == _hash_token(token),
            models.WebTelegramAuthAttempt.expires_at > now,
            models.WebTelegramAuthAttempt.completed_at.is_not(None),
            models.WebTelegramAuthAttempt.consumed_at.is_(None),
        )
    ).scalar_one_or_none()
    if record is None or record.user is None:
        return None
    user = record.user
    record.consumed_at = now
    db.commit()
    return user
