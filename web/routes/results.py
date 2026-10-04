"""Public read-only pages for imported Endstep tournament results."""

from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core import models
from web.auth import get_db
from web.templating import templates

router = APIRouter()


@router.get("/results", response_class=HTMLResponse)
async def results_list(request: Request, db: Session = Depends(get_db)):
    tournaments = (
        db.execute(select(models.EndstepTournament).order_by(models.EndstepTournament.imported_at.desc()))
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={"tournaments": tournaments},
    )


@router.get("/results/{slug}", response_class=HTMLResponse)
async def result_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    tournament = db.execute(
        select(models.EndstepTournament)
        .options(selectinload(models.EndstepTournament.standings).selectinload(models.EndstepStanding.user))
        .options(selectinload(models.EndstepTournament.pairings))
        .options(selectinload(models.EndstepTournament.deck_cards))
        .where(models.EndstepTournament.slug == slug)
    ).scalar_one_or_none()
    if tournament is None:
        return RedirectResponse("/results", status_code=303)

    cards_by_player: dict[str, dict[str, list[models.EndstepDeckCard]]] = defaultdict(
        lambda: {"Main": [], "Sideboard": []}
    )
    for card in tournament.deck_cards:
        cards_by_player[card.player_name][card.section].append(card)

    players = [
        {
            "standing": standing,
            "main": cards_by_player[standing.player_name]["Main"],
            "sideboard": cards_by_player[standing.player_name]["Sideboard"],
        }
        for standing in tournament.standings
    ]
    pairings_by_round: dict[int, list[models.EndstepPairing]] = defaultdict(list)
    for pairing in tournament.pairings:
        pairings_by_round[pairing.round_number].append(pairing)

    return templates.TemplateResponse(
        request=request,
        name="result_detail.html",
        context={
            "tournament": tournament,
            "players": players,
            "pairings_by_round": dict(sorted(pairings_by_round.items())),
        },
    )
