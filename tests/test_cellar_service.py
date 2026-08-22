from datetime import date, datetime

import pytest

from core import models
from core.schemas import TournamentCreate
from services.cellar import (
    BOOTSTRAP_CATALOG,
    CellarDeckUnavailable,
    CellarInvalidEventDate,
    CellarService,
    CellarUserAlreadyReserved,
    format_coordinator_summary,
    format_group_reservation,
    next_cellar_dates,
)
from services.tournament import TournamentService
from web.routes.settings import _merge_accounts

EVENT_DATE = date(2026, 8, 24)


def _catalog(db):
    service = CellarService(db)
    service.ensure_bootstrap_catalog()
    return service, service.catalog(EVENT_DATE)


def _edinorog_tournament(db):
    return TournamentService(db).create_tournament(
        TournamentCreate(
            title="Edinorog Pauper",
            chat_id=100,
            club="Edinorog",
            registration_close_at=datetime(2026, 8, 24, 16, 30),
        )
    )


def test_bootstrap_catalog_is_complete_and_idempotent(db):
    service = CellarService(db)

    assert service.ensure_bootstrap_catalog() == len(BOOTSTRAP_CATALOG)
    assert service.ensure_bootstrap_catalog() == 0
    assert len(service.catalog(EVENT_DATE)) == len(BOOTSTRAP_CATALOG)
    assert any(deck.notes == "Без камней" for deck in service.catalog(EVENT_DATE))


def test_next_cellar_dates_starts_with_current_or_next_monday():
    assert next_cellar_dates(date(2026, 8, 22), count=3) == [
        date(2026, 8, 24),
        date(2026, 8, 31),
        date(2026, 9, 7),
    ]
    assert next_cellar_dates(date(2026, 8, 24), count=1) == [date(2026, 8, 24)]


def test_reservation_is_exclusive_per_deck_and_user(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    bob = user_svc.get_or_create(tg_id=1002, first_name="Bob")

    first = service.reserve(deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE)
    repeated = service.reserve(deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE)

    assert first.created is True
    assert repeated.created is False
    with pytest.raises(CellarDeckUnavailable, match="другой игрок"):
        service.reserve(deck_id=decks[0].id, user_id=bob.id, event_date=EVENT_DATE, today=EVENT_DATE)
    with pytest.raises(CellarUserAlreadyReserved, match="другая колода"):
        service.reserve(deck_id=decks[1].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE)


def test_cancel_releases_deck_and_user_slot(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    bob = user_svc.get_or_create(tg_id=1002, first_name="Bob")
    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation

    service.cancel(reservation_id=reservation.id, user_id=alice.id)
    replacement = service.reserve(
        deck_id=decks[0].id, user_id=bob.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation

    assert replacement.user_id == bob.id
    assert reservation.cancelled_at is not None


def test_only_future_mondays_are_accepted(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")

    with pytest.raises(CellarInvalidEventDate):
        service.reserve(
            deck_id=decks[0].id,
            user_id=alice.id,
            event_date=date(2026, 8, 25),
            today=date(2026, 8, 22),
        )
    with pytest.raises(CellarInvalidEventDate):
        service.reserve(
            deck_id=decks[0].id,
            user_id=alice.id,
            event_date=date(2026, 8, 17),
            today=date(2026, 8, 22),
        )


def test_reservation_registers_player_in_existing_tournament_and_cancel_undoes_it(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    tournament = _edinorog_tournament(db)

    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation
    participant = TournamentService(db).get_participant(tournament.id, alice.id)

    assert participant is not None
    assert reservation.tournament_id == tournament.id
    assert reservation.participant_created is True
    assert db.get(models.Archetype, participant.archetype_id).name == decks[0].archetype_name

    service.cancel(reservation_id=reservation.id, user_id=alice.id)
    assert TournamentService(db).get_participant(tournament.id, alice.id) is None


def test_reservation_fills_but_does_not_remove_existing_empty_participant_on_cancel(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    tournament = _edinorog_tournament(db)
    participant = TournamentService(db).register_participant(tournament_id=tournament.id, user_id=alice.id)

    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation
    assert reservation.participant_created is False
    assert TournamentService(db).get_participant_by_id(participant.id).archetype_id is not None

    service.cancel(reservation_id=reservation.id, user_id=alice.id)
    saved = TournamentService(db).get_participant_by_id(participant.id)
    assert saved is not None
    assert saved.archetype_id is None


def test_reservation_temporarily_replaces_existing_deck_and_cancel_restores_it(db, user_svc, arch_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    tournament = _edinorog_tournament(db)
    own_deck = arch_svc.get_or_create_by_name("Own Deck")
    TournamentService(db).register_participant(
        tournament_id=tournament.id,
        user_id=alice.id,
        archetype_id=own_deck.id,
        deck_added_by_tg_id=alice.tg_id,
    )

    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation
    participant = TournamentService(db).get_participant(tournament.id, alice.id)

    assert participant.archetype_id == reservation.applied_archetype_id
    assert reservation.previous_archetype_id == own_deck.id
    assert reservation.tournament_id == tournament.id

    service.cancel(reservation_id=reservation.id, user_id=alice.id)
    assert TournamentService(db).get_participant(tournament.id, alice.id).archetype_id == own_deck.id


def test_pending_reservation_is_attached_when_tournament_is_created(db, user_svc):
    service, decks = _catalog(db)
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation
    tournament = _edinorog_tournament(db)

    assert service.attach_event_to_tournament(EVENT_DATE, tournament.id) == 1
    assert reservation.tournament_id == tournament.id
    assert TournamentService(db).get_participant(tournament.id, alice.id) is not None


def test_messages_contain_deck_date_and_players(db, user_svc):
    service, decks = _catalog(db)
    decks[0].source_position = 13
    db.commit()
    alice = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    reservation = service.reserve(
        deck_id=decks[0].id, user_id=alice.id, event_date=EVENT_DATE, today=EVENT_DATE
    ).reservation

    assert "Alice" in format_group_reservation(reservation)
    assert decks[0].name in format_group_reservation(reservation)
    assert "№13" in format_group_reservation(reservation)
    assert "24.08.2026" in format_coordinator_summary(EVENT_DATE, [reservation])
    assert "№13" in format_coordinator_summary(EVENT_DATE, [reservation])


def test_web_account_link_preserves_cellar_reservation(db, user_svc):
    service, decks = _catalog(db)
    web_user = models.User(tg_id=-1, email="player@example.test", first_name="Alice")
    db.add(web_user)
    db.commit()
    tg_user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    reservation = service.reserve(
        deck_id=decks[0].id,
        user_id=web_user.id,
        event_date=EVENT_DATE,
        today=EVENT_DATE,
    ).reservation

    _merge_accounts(db, web_user, tg_user)

    db.refresh(reservation)
    assert reservation.user_id == tg_user.id
    assert reservation.cancelled_at is None


def test_web_account_link_cancels_duplicate_active_date(db, user_svc):
    service, decks = _catalog(db)
    web_user = models.User(tg_id=-1, email="player@example.test", first_name="Alice")
    db.add(web_user)
    db.commit()
    tg_user = user_svc.get_or_create(tg_id=1001, first_name="Alice")
    web_reservation = service.reserve(
        deck_id=decks[0].id,
        user_id=web_user.id,
        event_date=EVENT_DATE,
        today=EVENT_DATE,
    ).reservation
    tg_reservation = service.reserve(
        deck_id=decks[1].id,
        user_id=tg_user.id,
        event_date=EVENT_DATE,
        today=EVENT_DATE,
    ).reservation

    _merge_accounts(db, web_user, tg_user)

    db.refresh(web_reservation)
    db.refresh(tg_reservation)
    assert web_reservation.user_id == tg_user.id
    assert web_reservation.cancelled_at is not None
    assert tg_reservation.cancelled_at is None
