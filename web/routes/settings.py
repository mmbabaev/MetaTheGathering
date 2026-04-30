from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from web.auth import get_current_user, get_db, make_session_cookie
from web.templating import templates

router = APIRouter()


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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="settings.html", context={"user": user})


@router.post("/settings")
async def settings_save(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
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


@router.post("/settings/link-tg/{tg_user_id}")
async def link_tg_account(
    tg_user_id: int,
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tg_user = db.get(models.User, tg_user_id)
    if not tg_user or tg_user.tg_id <= 0:
        return RedirectResponse("/settings", status_code=303)

    tg_user.email = user.email
    db.commit()

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
