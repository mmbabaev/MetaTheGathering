"""Low-volume, cached Scryfall metadata resolution for imported decklists."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
SCRYFALL_USER_AGENT = "MetaGatherer/1.0 (card preview resolver)"


class ScryfallResolveError(RuntimeError):
    """Scryfall returned a temporary or unexpected error."""


def normalize_card_name(value: str) -> str:
    return " ".join(value.split()).casefold()


class ScryfallCardResolver:
    """Resolve unique names once and keep image URLs in the local database.

    The default 120 ms spacing intentionally stays below the 10 requests/sec
    guidance even when this process is running close to its target rate.  Card
    images are never downloaded by this service; the browser loads them lazily
    from the returned Scryfall CDN URL.
    """

    def __init__(
        self,
        db: Session,
        *,
        session: requests.Session | None = None,
        min_interval_seconds: float = 0.12,
        timeout: int = 15,
    ) -> None:
        self.db = db
        self.session = session or requests.Session()
        self.min_interval_seconds = min_interval_seconds
        self.timeout = timeout
        self._last_request_at: float | None = None

    def resolve_tournament(self, tournament_id: int, *, force: bool = False) -> int:
        rows = (
            self.db.execute(
                select(models.EndstepDeckCard)
                .where(models.EndstepDeckCard.tournament_id == tournament_id)
                .order_by(models.EndstepDeckCard.id)
            )
            .scalars()
            .all()
        )
        names = sorted({row.normalized_name for row in rows})
        cached = {
            card.normalized_name: card
            for card in self.db.execute(
                select(models.ScryfallCard).where(models.ScryfallCard.normalized_name.in_(names))
            ).scalars()
        }

        for normalized_name in names:
            card = cached.get(normalized_name)
            if card is not None and not force and card.status in {"resolved", "unresolved"}:
                continue
            if card is None:
                card = models.ScryfallCard(normalized_name=normalized_name, status="pending")
                self.db.add(card)
                self.db.flush()
                cached[normalized_name] = card
            self._resolve_one(card, self._display_name_for(rows, normalized_name))

        for row in rows:
            card = cached.get(row.normalized_name)
            if card is None:
                continue
            row.scryfall_card_id = card.id
            row.scryfall_id = card.scryfall_id
            row.image_uri = card.image_uri
            row.image_uri_back = card.image_uri_back
        self.db.commit()
        return sum(1 for card in cached.values() if card.status == "resolved")

    @staticmethod
    def _display_name_for(rows: list[models.EndstepDeckCard], normalized_name: str) -> str:
        for row in rows:
            if row.normalized_name == normalized_name:
                return row.card_name
        return normalized_name

    def _resolve_one(self, card: models.ScryfallCard, display_name: str) -> None:
        self._wait_for_rate_limit()
        try:
            response = self.session.get(
                SCRYFALL_NAMED_URL,
                params={"exact": display_name},
                headers={"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            card.status = "error"
            card.error_message = "network error"
            raise ScryfallResolveError(f"Scryfall недоступен для карты {display_name}") from exc

        now = datetime.now(UTC).replace(tzinfo=None)
        card.resolved_at = now
        if response.status_code == 404:
            card.status = "unresolved"
            card.error_message = "not found"
            return
        if response.status_code >= 400:
            card.status = "error"
            card.error_message = f"HTTP {response.status_code}"
            raise ScryfallResolveError(f"Scryfall вернул HTTP {response.status_code} для {display_name}")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            card.status = "error"
            card.error_message = "invalid json"
            raise ScryfallResolveError("Scryfall вернул некорректный JSON") from exc

        image_uris = payload.get("image_uris") or {}
        faces = payload.get("card_faces") or []
        if not image_uris and faces:
            image_uris = (faces[0].get("image_uris") or {}) if isinstance(faces[0], dict) else {}
        back_image_uris = {}
        if len(faces) > 1 and isinstance(faces[1], dict):
            back_image_uris = faces[1].get("image_uris") or {}

        card.canonical_name = payload.get("name") or display_name
        card.scryfall_id = payload.get("id")
        card.image_uri = image_uris.get("normal") or image_uris.get("large")
        card.image_uri_back = back_image_uris.get("normal") or back_image_uris.get("large")
        card.status = "resolved" if card.image_uri else "unresolved"
        card.error_message = None if card.status == "resolved" else "image unavailable"

    def _wait_for_rate_limit(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()
