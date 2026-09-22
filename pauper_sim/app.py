"""FastAPI app for the Pauper Duel Simulator side project.

Serves the static frontend, the parsed winrate data (with caching) and small
JSON endpoints for pairing and rolling match games.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pauper_sim.logic import Player, pair_players, roll_game, win_probability
from pauper_sim.winrates import WINRATES_URL, WinrateCache, WinrateData

POOL_SIZE = 20
_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Pauper Duel Simulator", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
_winrate_cache = WinrateCache()


class PlayerIn(BaseModel):
    name: str
    deck: str


class PairIn(BaseModel):
    players: list[PlayerIn]


class RollIn(BaseModel):
    a: str
    b: str


def _serialize(data: WinrateData) -> dict:
    return {
        "source_url": WINRATES_URL,
        "fetched_at": datetime.fromtimestamp(data.fetched_at, tz=timezone.utc).isoformat(),
        "pool_size": POOL_SIZE,
        "decks": [
            {"name": deck.name, "overall_winrate": deck.overall_winrate, "matches": deck.matches} for deck in data.decks
        ],
        "matrix": data.matrix,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/winrates")
def api_winrates(force: bool = False) -> dict:
    try:
        data = _winrate_cache.get(force=force)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch winrates: {exc}") from exc
    return _serialize(data)


@app.post("/api/winrates/refresh")
def api_winrates_refresh() -> dict:
    try:
        data = _winrate_cache.get(force=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch winrates: {exc}") from exc
    return _serialize(data)


@app.post("/api/roll")
def api_roll(body: RollIn) -> dict:
    try:
        data = _winrate_cache.get()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch winrates: {exc}") from exc
    winner = roll_game(body.a, body.b, data, random.Random())
    return {
        "winner": winner,
        "probability_pct": round(win_probability(body.a, body.b, data), 1),
    }


@app.post("/api/pair")
def api_pair(body: PairIn) -> dict:
    if len(body.players) < 2:
        raise HTTPException(status_code=400, detail="Нужно минимум 2 игрока")
    players = [Player(name=player.name, deck=player.deck) for player in body.players]
    matches, bye = pair_players(players, random.Random())
    return {
        "matches": [{"a": {"name": a.name, "deck": a.deck}, "b": {"name": b.name, "deck": b.deck}} for a, b in matches],
        "bye": {"name": bye.name, "deck": bye.deck} if bye else None,
    }
