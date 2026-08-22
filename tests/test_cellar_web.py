from datetime import date
from unittest.mock import AsyncMock
from urllib.parse import unquote

import pytest
from sqlalchemy import select

from core import models
from services.cellar import CellarService
from web.app import app
from web.routes.cellar import cancel_cellar_reservation, reserve_cellar_deck
from web.templating import templates

EVENT_DATE = date(2026, 8, 24)


def _deck(db):
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    return service.catalog(EVENT_DATE)[0]


@pytest.mark.asyncio
async def test_web_reservation_announces_once_and_marks_delivery(db, user_svc, monkeypatch):
    user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    deck = _deck(db)
    announce = AsyncMock(return_value=True)
    monkeypatch.setattr("web.routes.cellar._announce", announce)

    response = await reserve_cellar_deck(deck.id, EVENT_DATE, user=user, db=db)
    repeated = await reserve_cellar_deck(deck.id, EVENT_DATE, user=user, db=db)

    assert response.status_code == 303
    assert "message=" in response.headers["location"]
    reservation = db.execute(select(models.CellarDeckReservation)).scalar_one()
    assert reservation.group_announced_at is not None
    announce.assert_awaited_once_with(reservation)
    assert "уже" in unquote(repeated.headers["location"])


@pytest.mark.asyncio
async def test_web_reservation_conflict_does_not_announce(db, user_svc, monkeypatch):
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    bob = user_svc.get_or_create(tg_id=1002, first_name="Bob")
    deck = _deck(db)
    CellarService(db).reserve(deck_id=deck.id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE)
    announce = AsyncMock(return_value=True)
    monkeypatch.setattr("web.routes.cellar._announce", announce)

    response = await reserve_cellar_deck(deck.id, EVENT_DATE, user=bob, db=db)

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    announce.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_cancel_releases_only_own_reservation_and_announces(db, user_svc, monkeypatch):
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    bob = user_svc.get_or_create(tg_id=1002, first_name="Bob")
    deck = _deck(db)
    reservation = (
        CellarService(db)
        .reserve(
            deck_id=deck.id,
            user_id=alice.id,
            event_date=EVENT_DATE,
            today=EVENT_DATE,
        )
        .reservation
    )
    announce = AsyncMock(return_value=True)
    monkeypatch.setattr("web.routes.cellar._announce", announce)

    denied = await cancel_cellar_reservation(reservation.id, EVENT_DATE, user=bob, db=db)
    response = await cancel_cellar_reservation(reservation.id, EVENT_DATE, user=alice, db=db)

    assert "error=" in denied.headers["location"]
    assert "message=" in response.headers["location"]
    assert reservation.cancelled_at is not None
    announce.assert_awaited_once_with(reservation, cancelled=True)


def test_cellar_page_renders_availability_and_reserver(db, user_svc):
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    decks = service.catalog(EVENT_DATE)
    service.reserve(deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE)
    db.expire_all()
    decks = service.catalog(EVENT_DATE)

    html = templates.get_template("cellar.html").render(
        user=alice,
        dates=[EVENT_DATE],
        selected_date=EVENT_DATE,
        decks=decks,
        my_reservation=service.reservation_for(decks[0], EVENT_DATE),
        reservation_for=service.reservation_for,
        message=None,
        error=None,
    )

    assert "Колоды из ячейки" in html
    assert "Забронировал(а): Alice" in html
    assert "Занята" in html


def test_cellar_routes_are_registered():
    paths = {path for route in app.routes if (path := getattr(route, "path", None)) is not None}
    assert "/cellar" in paths
    assert "/cellar/{deck_id}/reserve" in paths
    assert "/cellar/reservations/{reservation_id}/cancel" in paths
