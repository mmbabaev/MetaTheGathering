from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core import models
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from services.user import UserService
from web.auth import get_current_user, get_db
from web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def tournament_list(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = (
        select(models.Tournament)
        .where(models.Tournament.status != models.TournamentStatus.CLOSED)
        .order_by(models.Tournament.created_at.desc())
    )
    tournaments = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request=request, name="tournaments.html", context={"user": user, "tournaments": tournaments}
    )


@router.get("/t/{tournament_id}", response_class=HTMLResponse)
async def tournament_detail(
    request: Request, tournament_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    tournament = db.execute(
        select(models.Tournament)
        .options(selectinload(models.Tournament.participants).selectinload(models.Participant.user))
        .options(selectinload(models.Tournament.participants).selectinload(models.Participant.archetype))
        .where(models.Tournament.id == tournament_id)
    ).scalar_one_or_none()
    if not tournament:
        return RedirectResponse("/", status_code=303)

    archetypes = (
        db.execute(
            select(models.Archetype)
            .where(models.Archetype.is_custom == False)  # noqa: E712
            .order_by(models.Archetype.meta_rank.nulls_last(), models.Archetype.name)
        )
        .scalars()
        .all()
    )

    my_participant = next((p for p in tournament.participants if p.user_id == user.id), None)
    return templates.TemplateResponse(
        request=request,
        name="tournament.html",
        context={
            "user": user,
            "tournament": tournament,
            "archetypes": archetypes,
            "my_participant": my_participant,
        },
    )


@router.post("/t/{tournament_id}/register")
async def register(
    tournament_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    archetype_id: int = Form(default=0),
    custom_archetype: str = Form(default=""),
):
    arch_svc = ArchetypeService(db)
    tournament_svc = TournamentService(db)

    resolved_archetype_id = archetype_id
    if archetype_id == -1 and custom_archetype.strip():
        archetype = arch_svc.get_or_create_by_name(custom_archetype.strip(), is_custom=True)
        resolved_archetype_id = archetype.id

    if resolved_archetype_id and resolved_archetype_id > 0:
        tournament_svc.register_participant(
            tournament_id=tournament_id,
            user_id=user.id,
            archetype_id=resolved_archetype_id,
            deck_added_by_tg_id=user.tg_id,
        )
    return RedirectResponse(f"/t/{tournament_id}", status_code=303)


@router.post("/t/{tournament_id}/unregister")
async def unregister(tournament_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    TournamentService(db).unregister_participant(tournament_id=tournament_id, user_id=user.id)
    return RedirectResponse(f"/t/{tournament_id}", status_code=303)


@router.post("/t/{tournament_id}/register-opponent")
async def register_opponent(
    tournament_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
    opponent_name: str = Form(...),
    archetype_id: int = Form(default=0),
    custom_archetype: str = Form(default=""),
):
    arch_svc = ArchetypeService(db)
    user_svc = UserService(db)
    tournament_svc = TournamentService(db)

    first, *rest = opponent_name.strip().split(None, 1)
    last = rest[0] if rest else None
    opponent, _ = user_svc.get_or_create_by_name(first, last)
    db.commit()

    resolved_archetype_id = archetype_id
    if archetype_id == -1 and custom_archetype.strip():
        archetype = arch_svc.get_or_create_by_name(custom_archetype.strip(), is_custom=True)
        resolved_archetype_id = archetype.id

    if resolved_archetype_id and resolved_archetype_id > 0:
        tournament_svc.register_participant(
            tournament_id=tournament_id,
            user_id=opponent.id,
            archetype_id=resolved_archetype_id,
            deck_added_by_tg_id=user.tg_id,
        )
    return RedirectResponse(f"/t/{tournament_id}", status_code=303)
