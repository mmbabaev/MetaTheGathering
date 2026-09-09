"""Guards for the one-to-one MetaGatherer ↔ AetherHub tournament link."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services import errors

_ROUND_TOURNAMENT_PATH_RE = re.compile(r"/Tourney/RoundTourney/(\d+)/?", re.IGNORECASE)
_AETHERHUB_HOSTS = {"aetherhub.com", "www.aetherhub.com"}


def aetherhub_tournament_key(url: str) -> tuple[str, str]:
    """Return a stable identity for a tournament URL.

    AetherHub may append a round query (``?p=2``), use ``www`` or leave a trailing
    slash. Those forms still identify the same numeric RoundTourney event. Unknown
    URL shapes fall back to exact trimmed-string comparison so the guard remains
    useful without accidentally conflating unrelated links.
    """
    normalized = url.strip()
    parsed = urlsplit(normalized)
    match = _ROUND_TOURNAMENT_PATH_RE.fullmatch(parsed.path)
    if parsed.hostname and parsed.hostname.casefold() in _AETHERHUB_HOSTS and match:
        return ("round_tournament", str(int(match.group(1))))
    return ("url", normalized.rstrip("/"))


def find_aetherhub_link_conflict(
    db: Session,
    *,
    tournament_id: int,
    url: str,
) -> models.Tournament | None:
    """Find another MetaGatherer tournament already linked to this AetherHub event."""
    requested_key = aetherhub_tournament_key(url)
    linked = db.execute(
        select(models.Tournament)
        .where(
            models.Tournament.id != tournament_id,
            models.Tournament.aetherhub_url.is_not(None),
        )
        .order_by(models.Tournament.id)
    ).scalars()
    return next(
        (tournament for tournament in linked if aetherhub_tournament_key(tournament.aetherhub_url) == requested_key),
        None,
    )


def ensure_aetherhub_link_available(db: Session, *, tournament_id: int, url: str) -> None:
    """Reject a link already owned by a different MetaGatherer tournament."""
    conflict = find_aetherhub_link_conflict(db, tournament_id=tournament_id, url=url)
    if conflict is not None:
        raise errors.AetherhubTournamentAlreadyLinked(
            url=url,
            tournament_id=conflict.id,
            tournament_title=conflict.title,
        )
