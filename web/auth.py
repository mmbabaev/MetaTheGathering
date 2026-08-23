from fastapi import Cookie, Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.config import settings
from core.database import SessionLocal

SESSION_TTL_DAYS = 90
_signer = URLSafeTimedSerializer(settings.WEB_SECRET_KEY, salt="web-session")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def make_session_cookie(user_id: int) -> str:
    return _signer.dumps(user_id)


def decode_session_cookie(cookie: str) -> int | None:
    try:
        max_age = SESSION_TTL_DAYS * 24 * 3600
        return _signer.loads(cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    web_session: str | None = Cookie(default=None),
) -> models.User:
    if web_session:
        user_id = decode_session_cookie(web_session)
        if user_id:
            user = db.get(models.User, user_id)
            if user:
                return user
    raise HTTPException(status_code=303, headers={"Location": "/login"})


def get_current_user_optional(
    db: Session = Depends(get_db),
    web_session: str | None = Cookie(default=None),
) -> models.User | None:
    if web_session:
        user_id = decode_session_cookie(web_session)
        if user_id:
            return db.get(models.User, user_id)
    return None


def get_or_create_web_user(db: Session, email: str) -> models.User:
    stmt = select(models.User).where(models.User.email == email)
    user = db.execute(stmt).scalar_one_or_none()
    if user:
        return user

    # Negative tg_id — same placeholder pattern used for opponents
    min_val = db.execute(select(func.min(models.User.tg_id))).scalar()
    placeholder_tg_id = (min_val - 1) if (min_val is not None and min_val < 0) else -1

    user = models.User(tg_id=placeholder_tg_id, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
