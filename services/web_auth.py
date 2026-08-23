"""One-time web authentication tokens shared by Telegram and web entry points."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

MAGIC_LINK_TTL_MINUTES = 15


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
