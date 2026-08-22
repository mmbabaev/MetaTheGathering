from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from core.config import app_cfg
from services.cellar import (
    CellarReservationError,
    CellarService,
    format_group_reservation,
    next_cellar_dates,
)
from services.cellar_sheet import CELLAR_SHEET_URL
from web.auth import get_current_user, get_db
from web.templating import templates
from web.tg_sender import send_tg_message

router = APIRouter(prefix="/cellar")


def _redirect(event_date: date, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = [f"event_date={event_date.isoformat()}"]
    if message:
        params.append(f"message={quote(message)}")
    if error:
        params.append(f"error={quote(error)}")
    return RedirectResponse(f"/cellar?{'&'.join(params)}", status_code=303)


async def _announce(reservation, *, cancelled: bool = False) -> bool:
    chat_id = app_cfg.edinorog_chat_id
    if not chat_id:
        return False
    return await send_tg_message(chat_id, format_group_reservation(reservation, cancelled=cancelled))


@router.get("", response_class=HTMLResponse)
async def cellar_catalog(
    request: Request,
    event_date: date | None = None,
    message: str | None = None,
    error: str | None = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dates = next_cellar_dates()
    selected_date = event_date if event_date in dates else dates[0]
    service = CellarService(db)
    decks = service.catalog(selected_date)
    my_reservation = next(
        (
            reservation
            for deck in decks
            if (reservation := service.reservation_for(deck, selected_date)) is not None
            and reservation.user_id == user.id
        ),
        None,
    )
    return templates.TemplateResponse(
        request=request,
        name="cellar.html",
        context={
            "user": user,
            "dates": dates,
            "selected_date": selected_date,
            "decks": decks,
            "my_reservation": my_reservation,
            "reservation_for": service.reservation_for,
            "catalog_source_url": CELLAR_SHEET_URL,
            "message": message,
            "error": error,
        },
    )


@router.post("/{deck_id}/reserve")
async def reserve_cellar_deck(
    deck_id: int,
    event_date: date = Form(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = CellarService(db)
    try:
        result = service.reserve(deck_id=deck_id, user_id=user.id, event_date=event_date)
    except CellarReservationError as exc:
        return _redirect(event_date, error=str(exc))
    if not result.created:
        return _redirect(event_date, message="Эта колода уже забронирована вами.")
    if await _announce(result.reservation):
        service.mark_group_announced(result.reservation.id)
    return _redirect(event_date, message="Колода забронирована.")


@router.post("/reservations/{reservation_id}/cancel")
async def cancel_cellar_reservation(
    reservation_id: int,
    event_date: date = Form(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = CellarService(db)
    try:
        reservation = service.cancel(reservation_id=reservation_id, user_id=user.id)
    except CellarReservationError as exc:
        return _redirect(event_date, error=str(exc))
    await _announce(reservation, cancelled=True)
    return _redirect(event_date, message="Бронь отменена.")
