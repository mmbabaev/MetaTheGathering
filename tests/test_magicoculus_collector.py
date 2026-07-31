from datetime import datetime
from unittest.mock import MagicMock

import pytest

from core import models
from core.schemas import TournamentCreate
from services.aetherhub_models import AetherhubTournamentData
from services.magicoculus import MagicOculusCollectionError, MagicOculusTournamentCollector


def _tournament(svc, db, *, club="Goldfish", url="https://aetherhub.com/Tourney/RoundTourney/42"):
    created = svc.create_tournament(TournamentCreate(title="Pauper", chat_id=100, club=club))
    row = db.get(models.Tournament, created.id)
    row.started_at = datetime(2026, 7, 24, 19, 30)
    row.aetherhub_url = url
    db.commit()
    return row


def _participant(db, tournament, user, archetype, *, place):
    row = models.Participant(
        tournament_id=tournament.id,
        user_id=user.id,
        archetype_id=archetype.id if archetype else None,
        final_place=place,
    )
    db.add(row)
    db.commit()
    return row


def test_collects_complete_tournament(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    alice = user_svc.get_or_create(tg_id=1, username="alice", first_name="Алиса", last_name="Иванова")
    bob = user_svc.get_or_create(tg_id=2, username="bob", first_name="Боб", last_name="Петров")
    burn = arch_svc.get_or_create_by_name("Mono Red Madness")
    elves = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, alice, burn, place=2)
    _participant(db, tournament, bob, elves, place=1)

    result = MagicOculusTournamentCollector(db).collect(tournament.id)

    assert result.date.isoformat() == "2026-07-24"
    assert result.club == "Goldfish"
    assert str(result.aetherhub_url) == "https://aetherhub.com/Tourney/RoundTourney/42"
    assert result.player_decks_text == "Петров Боб - Elves\nИванова Алиса - Mono Red Madness"
    assert [row.final_place for row in result.player_decks] == [1, 2]


@pytest.mark.parametrize(
    ("club", "url", "message"),
    [
        (None, "https://aetherhub.com/Tourney/RoundTourney/42", "не указан клуб"),
    ],
)
def test_requires_tournament_metadata(db, svc, club, url, message):
    tournament = _tournament(svc, db, club=club, url=url)

    with pytest.raises(MagicOculusCollectionError, match=message):
        MagicOculusTournamentCollector(db).collect(tournament.id)


def test_finds_historical_aetherhub_url_by_club_and_date(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db, club="Goldfish", url=None)
    player = user_svc.get_or_create(tg_id=1, username="alice", first_name="Алиса", last_name="Иванова")
    deck = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, player, deck, place=1)
    aetherhub = MagicMock()
    aetherhub.find_todays_pauper_tournament.return_value = "https://aetherhub.com/Tourney/RoundTourney/20260724"

    result = MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id)

    assert str(result.aetherhub_url).endswith("/20260724")
    aetherhub.find_todays_pauper_tournament.assert_called_once_with(
        "https://aetherhub.com/User/GoldFish", today=result.date
    )


def test_reports_missing_historical_aetherhub_tournament(db, svc):
    tournament = _tournament(svc, db, club="Goldfish", url=None)
    aetherhub = MagicMock()
    aetherhub.find_todays_pauper_tournament.return_value = None

    with pytest.raises(MagicOculusCollectionError, match="не найден Pauper-турнир"):
        MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id)


def test_reports_every_player_without_deck(db, svc, user_svc):
    tournament = _tournament(svc, db)
    alice = user_svc.get_or_create(tg_id=1, username="alice", first_name="Алиса", last_name="Иванова")
    bob = user_svc.get_or_create(tg_id=2, username="bob", first_name="Боб", last_name="Петров")
    _participant(db, tournament, alice, None, place=1)
    _participant(db, tournament, bob, None, place=2)

    with pytest.raises(MagicOculusCollectionError) as error:
        MagicOculusTournamentCollector(db).collect(tournament.id)

    assert "Иванова Алиса" in str(error.value)
    assert "Петров Боб" in str(error.value)


def test_rejects_duplicate_display_names(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    first = user_svc.get_or_create(tg_id=1, username="first", first_name="Иван", last_name="Иванов")
    second = user_svc.get_or_create(tg_id=2, username="second", first_name="Иван", last_name="Иванов")
    deck = arch_svc.get_or_create_by_name("Burn")
    _participant(db, tournament, first, deck, place=1)
    _participant(db, tournament, second, deck, place=2)

    with pytest.raises(MagicOculusCollectionError, match="встречается несколько раз"):
        MagicOculusTournamentCollector(db).collect(tournament.id)


def test_validates_player_count_against_aetherhub(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    player = user_svc.get_or_create(tg_id=1, username="alice", first_name="Алиса", last_name="Иванова")
    deck = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, player, deck, place=1)
    aetherhub = MagicMock()
    aetherhub.fetch_tournament.return_value = AetherhubTournamentData(
        url=tournament.aetherhub_url,
        players=[],
        rounds=[],
        standings=["Иванова Алиса", "Лишний Игрок"],
    )

    with pytest.raises(MagicOculusCollectionError, match="MetaGatherer 1 колод.*AetherHub 2"):
        MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id, validate_aetherhub=True)
