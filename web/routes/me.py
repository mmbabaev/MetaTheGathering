from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core import models
from services.cellar import CELLAR_TIMEZONE
from web.auth import get_current_user, get_db
from web.templating import templates

router = APIRouter()


@router.get("/me", response_class=HTMLResponse)
async def my_registrations(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    participants = (
        db.execute(
            select(models.Participant)
            .options(selectinload(models.Participant.tournament))
            .options(selectinload(models.Participant.archetype))
            .where(models.Participant.user_id == user.id)
            .order_by(models.Participant.created_at.desc())
        )
        .scalars()
        .all()
    )
    today = datetime.now(CELLAR_TIMEZONE).date()
    cellar_reservations = (
        db.execute(
            select(models.CellarDeckReservation)
            .options(selectinload(models.CellarDeckReservation.deck))
            .where(
                models.CellarDeckReservation.user_id == user.id,
                models.CellarDeckReservation.event_date >= today,
                models.CellarDeckReservation.cancelled_at.is_(None),
            )
            .order_by(models.CellarDeckReservation.event_date)
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="me.html",
        context={"user": user, "participants": participants, "cellar_reservations": cellar_reservations},
    )
