from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core import models
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
    return templates.TemplateResponse(
        request=request, name="me.html", context={"user": user, "participants": participants}
    )
