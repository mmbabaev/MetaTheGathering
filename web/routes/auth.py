from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from bot.deeplink import web_login_deeplink
from core.config import settings
from services.web_auth import (
    consume_telegram_auth_attempt,
    create_magic_token,
    create_telegram_auth_attempt,
    telegram_auth_attempt_status,
    verify_magic_token,
)
from web.auth import (
    get_current_user_optional,
    get_db,
    get_or_create_web_user,
    make_session_cookie,
)
from web.email import send_magic_link
from web.templating import templates

router = APIRouter()


def _safe_redirect(value: str | None) -> str:
    """Keep post-login redirects on this site, including against ``//host`` URLs."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html")


@router.get("/auth/telegram/start", response_class=HTMLResponse)
async def telegram_login_start(request: Request, next: str | None = None, db: Session = Depends(get_db)):
    if not settings.TELEGRAM_BOT_USERNAME:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Вход через Telegram пока не настроен."},
        )

    token = create_telegram_auth_attempt(db)
    bot_url = web_login_deeplink(settings.TELEGRAM_BOT_USERNAME, token)
    redirect_to = _safe_redirect(next)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "telegram_login": True,
            "telegram_url": bot_url,
            "telegram_poll_token": token,
            "redirect_to": redirect_to,
        },
    )


@router.get("/auth/telegram/status")
async def telegram_login_status(
    token: str,
    next: str | None = None,
    db: Session = Depends(get_db),
):
    status, user = telegram_auth_attempt_status(db, token)
    if status == "expired":
        raise HTTPException(status_code=410, detail="Ссылка для входа истекла")
    if status == "pending" or user is None:
        return {"status": "pending"}

    redirect_to = _safe_redirect(next)
    response = {"status": "authenticated", "redirect": redirect_to}
    # The browser follows the redirect value after this response. The actual cookie
    # is issued by a dedicated endpoint to keep the polling response JSON-only.
    return response


@router.get("/auth/telegram/complete")
async def telegram_login_complete(
    token: str,
    next: str | None = None,
    db: Session = Depends(get_db),
):
    user = consume_telegram_auth_attempt(db, token)
    if user is None:
        return RedirectResponse("/login?error=telegram_login_expired", status_code=303)
    redirect_to = _safe_redirect(next)
    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(
        "web_session",
        make_session_cookie(user.id),
        max_age=90 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.WEB_BASE_URL.startswith("https://"),
    )
    return response


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = get_or_create_web_user(db, email)
    token = create_magic_token(db, user)
    magic_url = f"{settings.WEB_BASE_URL}/auth/verify?token={token}"
    debug_link = await send_magic_link(email, magic_url) if settings.DEBUG else None
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "sent": bool(settings.SMTP_HOST or debug_link),
            "email": email,
            "debug_link": debug_link,
            "error": None if settings.SMTP_HOST or debug_link else "Почтовый вход временно недоступен.",
        },
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
        secure=settings.WEB_BASE_URL.startswith("https://"),
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("web_session")
    return response
