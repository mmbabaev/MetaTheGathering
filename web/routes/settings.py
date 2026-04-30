import random
import string
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models
from core.models import utc_now
from web.auth import get_current_user, get_db, make_session_cookie
from web.templating import templates
from web.tg_sender import send_tg_message

router = APIRouter()

LINK_CODE_TTL_MINUTES = 15


def _find_tg_match(db: Session, first_name: str, last_name: str) -> models.User | None:
    if not first_name or not last_name:
        return None
    return db.execute(
        select(models.User).where(
            models.User.first_name == first_name,
            models.User.last_name == last_name,
            models.User.tg_id > 0,
        )
    ).scalar_one_or_none()


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def _merge_accounts(db: Session, web_user: models.User, tg_user: models.User) -> None:
    """Transfer email and participants from web_user to tg_user, then delete web_user."""
    tg_user.email = web_user.email

    # Move participants, skip on tournament conflict (tg_user already registered there)
    existing_tournaments = {
        p.tournament_id
        for p in db.execute(select(models.Participant).where(models.Participant.user_id == tg_user.id)).scalars()
    }
    db.execute(
        update(models.Participant)
        .where(
            models.Participant.user_id == web_user.id,
            models.Participant.tournament_id.not_in(existing_tournaments),
        )
        .values(user_id=tg_user.id)
    )

    db.delete(web_user)
    db.commit()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user=Depends(get_current_user),
    link_pending: int | None = None,
    db: Session = Depends(get_db),
):
    pending_request = None
    if link_pending and user.tg_id < 0:
        pending_request = db.execute(
            select(models.WebLinkRequest).where(
                models.WebLinkRequest.id == link_pending,
                models.WebLinkRequest.web_user_id == user.id,
                models.WebLinkRequest.used_at.is_(None),
                models.WebLinkRequest.expires_at > utc_now(),
            )
        ).scalar_one_or_none()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"user": user, "pending_request": pending_request},
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    first_name: str = Form(...),
    last_name: str = Form(...),
):
    first_name = first_name.strip()
    last_name = last_name.strip()
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    db.commit()

    if user.tg_id < 0:
        tg_match = _find_tg_match(db, first_name, last_name)
        if tg_match:
            return templates.TemplateResponse(
                request=request,
                name="settings.html",
                context={"user": user, "tg_match": tg_match},
            )

    return RedirectResponse("/", status_code=303)


@router.post("/settings/request-link/{tg_user_id}")
async def request_link(
    tg_user_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tg_user = db.get(models.User, tg_user_id)
    if not tg_user or tg_user.tg_id <= 0:
        return RedirectResponse("/settings", status_code=303)

    code = _generate_code()
    link_req = models.WebLinkRequest(
        web_user_id=user.id,
        tg_user_id=tg_user.id,
        code=code,
        expires_at=utc_now() + timedelta(minutes=LINK_CODE_TTL_MINUTES),
    )
    db.add(link_req)
    db.commit()
    db.refresh(link_req)

    await send_tg_message(
        tg_user.tg_id,
        f"Кто-то хочет привязать email {user.email} к вашему аккаунту MetaGatherer.\n\n"
        f"Если это вы — введите код на сайте:\n\n{code}\n\n"
        f"Код действителен {LINK_CODE_TTL_MINUTES} минут. Если вы не запрашивали привязку — проигнорируйте.",
    )

    return RedirectResponse(f"/settings?link_pending={link_req.id}", status_code=303)


@router.post("/settings/verify-link")
async def verify_link(
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    link_request_id: int = Form(...),
    code: str = Form(...),
):
    link_req = db.execute(
        select(models.WebLinkRequest).where(
            models.WebLinkRequest.id == link_request_id,
            models.WebLinkRequest.web_user_id == user.id,
            models.WebLinkRequest.used_at.is_(None),
            models.WebLinkRequest.expires_at > utc_now(),
        )
    ).scalar_one_or_none()

    if not link_req or link_req.code != code.strip():
        pending_request = link_req
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={"user": user, "pending_request": pending_request, "code_error": True},
        )

    link_req.used_at = utc_now()
    tg_user = db.get(models.User, link_req.tg_user_id)
    _merge_accounts(db, user, tg_user)

    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        "web_session",
        make_session_cookie(tg_user.id),
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/settings/skip-link")
async def skip_link():
    return RedirectResponse("/", status_code=303)
