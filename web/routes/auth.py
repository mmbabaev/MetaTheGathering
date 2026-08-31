from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from core.config import settings
from services.web_auth import create_magic_token, verify_magic_token
from web.auth import (
    get_current_user_optional,
    get_db,
    get_or_create_web_user,
    make_session_cookie,
)
from web.email import send_magic_link
from web.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html")


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = get_or_create_web_user(db, email)
    token = create_magic_token(db, user)
    magic_url = f"{settings.WEB_BASE_URL}/auth/verify?token={token}"
    debug_link = await send_magic_link(email, magic_url)
    return templates.TemplateResponse(
        request=request, name="login.html", context={"sent": True, "email": email, "debug_link": debug_link}
    )


@router.get("/auth/verify", response_class=HTMLResponse)
async def auth_verify(request: Request, token: str, next: str | None = None, db: Session = Depends(get_db)):
    user = verify_magic_token(db, token)
    if not user:
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": "Ссылка недействительна или истекла."}
        )

    needs_name = not (user.display_name or user.first_name)
    redirect_to = "/settings" if needs_name else "/cellar" if next == "/cellar" else "/"

    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(
        "web_session",
        make_session_cookie(user.id),
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("web_session")
    return response
