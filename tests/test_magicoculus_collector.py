from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from core import models
from core.schemas import TournamentCreate
from services.aetherhub_models import AetherhubTournamentData
from services.internal_swiss import InternalSwissService
from services.magicoculus import (
    MagicOculusCollectionError,
    MagicOculusPlayerDeck,
    MagicOculusTournament,
    MagicOculusTournamentCollector,
)


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


def _completed_internal_swiss(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db, club="Endstep-ru", url=None)
    tournament.engine_mode = models.TournamentEngineMode.INTERNAL_SWISS
    tournament.status = models.TournamentStatus.ONGOING
    tournament.swiss_rounds = 4
    users = [
        user_svc.get_or_create(tg_id=index, first_name=first, last_name=last)
        for index, (first, last) in enumerate(
            (("Алиса", "Иванова"), ("Борис", "Петров"), ("Вера", "Сидорова")),
            start=1,
        )
    ]
    decks = [arch_svc.get_or_create_by_name(name) for name in ("Elves", "Burn", "Familiars")]
    participants = []
    for initial_rank, (user, deck) in enumerate(zip(users, decks), start=1):
        participant = _participant(db, tournament, user, deck, place=initial_rank)
        participant.swiss_initial_rank = initial_rank
        participants.append(participant)

    pairings = (
        (1, 1, users[0], users[1], 2, 0),
        (1, 2, users[2], None, 2, 0),
        (2, 1, users[0], users[2], 2, 1),
        (2, 2, users[1], None, 2, 0),
        (3, 1, users[1], users[2], 2, 0),
        (3, 2, users[0], None, 2, 0),
        (4, 1, users[0], users[1], 1, 1),
        (4, 2, users[2], None, 2, 0),
    )
    for round_number, table_number, left, right, left_wins, right_wins in pairings:
        db.add(
            models.RoundMatch(
                tournament_id=tournament.id,
                round_number=round_number,
                table_number=table_number,
                pairing_key=f"r{round_number}t{table_number}",
                player1_name=f"{left.last_name} {left.first_name}",
                player2_name=f"{right.last_name} {right.first_name}" if right else None,
                player1_user_id=left.id,
                player2_user_id=right.id if right else None,
                player1_wins=left_wins,
                player2_wins=right_wins,
                status=models.RoundMatchStatus.ADMIN,
            )
        )
    db.commit()
    standings = InternalSwissService(db).standings(tournament.id)
    participants_by_id = {participant.id: participant for participant in participants}
    for standing in standings:
        participants_by_id[standing.participant_id].final_place = standing.place
    tournament.status = models.TournamentStatus.CLOSED
    db.commit()
    return tournament


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


def test_collects_closed_internal_swiss_as_two_csv_files(db, svc, user_svc, arch_svc):
    tournament = _completed_internal_swiss(db, svc, user_svc, arch_svc)
    aetherhub = MagicMock()

    result = MagicOculusTournamentCollector(db, aetherhub).collect(
        tournament.id,
        validate_aetherhub=True,
    )

    assert result.source_kind == "internal_swiss"
    assert result.aetherhub_url is None
    assert result.final_standings_csv.startswith("Rank,Name,Points,Results,OMW,GW,OGW\r\n")
    assert "Иванова Алиса" in result.final_standings_csv
    assert result.all_rounds_csv.startswith("Table,Player 1,Player 2,Match Results\r\n")
    assert "2,Сидорова Вера,BYE,2 - 0" in result.all_rounds_csv
    assert result.all_rounds_csv.count("\r\n") == 9
    assert [row.final_place for row in result.player_decks] == [1, 2, 3]
    aetherhub.find_todays_pauper_tournament.assert_not_called()
    aetherhub.fetch_tournament.assert_not_called()


def test_internal_swiss_must_be_closed_before_collection(db, svc, user_svc, arch_svc):
    tournament = _completed_internal_swiss(db, svc, user_svc, arch_svc)
    tournament.status = models.TournamentStatus.ONGOING
    db.commit()

    with pytest.raises(MagicOculusCollectionError, match="только после завершения"):
        MagicOculusTournamentCollector(db).collect(tournament.id)


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


def test_aetherhub_validation_excludes_registered_no_shows(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    played = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
    no_show = user_svc.get_or_create(tg_id=2, first_name="Сергей", last_name="Егоров")
    deck = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, played, deck, place=1)
    _participant(db, tournament, no_show, deck, place=None)
    aetherhub = MagicMock()
    aetherhub.fetch_tournament.return_value = AetherhubTournamentData(
        url=tournament.aetherhub_url,
        players=[],
        rounds=[],
        standings=["Иванова Алиса"],
    )

    result = MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id, validate_aetherhub=True)

    assert [row.player for row in result.player_decks] == ["Иванова Алиса"]


def test_aetherhub_validation_accepts_unique_single_letter_name_typo(db, svc, user_svc, arch_svc):
    """Issue #233: AetherHub «Констанин» matches registered «Константин»."""
    tournament = _tournament(svc, db)
    player = user_svc.get_or_create(tg_id=233, first_name="Константин", last_name="Бурбаев")
    deck = arch_svc.get_or_create_by_name("Jeskai Ephemerate")
    _participant(db, tournament, player, deck, place=1)
    aetherhub = MagicMock()
    aetherhub.fetch_tournament.return_value = AetherhubTournamentData(
        url=tournament.aetherhub_url,
        players=[],
        rounds=[],
        standings=["Бурбаев Констанин"],
    )

    result = MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id, validate_aetherhub=True)

    assert result.player_decks == [
        MagicOculusPlayerDeck(player="Бурбаев Константин", deck="Jeskai Ephemerate", final_place=1)
    ]


def test_aetherhub_validation_rejects_ambiguous_single_letter_name_typo(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    deck = arch_svc.get_or_create_by_name("Burn")
    for tg_id, first_name, place in ((234, "Мария", 1), (235, "Марина", 2)):
        player = user_svc.get_or_create(tg_id=tg_id, first_name=first_name, last_name="Иванова")
        _participant(db, tournament, player, deck, place=place)
    aetherhub = MagicMock()
    aetherhub.fetch_tournament.return_value = AetherhubTournamentData(
        url=tournament.aetherhub_url,
        players=[],
        rounds=[],
        standings=["Иванова Мариа"],
    )

    with pytest.raises(MagicOculusCollectionError):
        MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id, validate_aetherhub=True)


def test_no_show_without_deck_does_not_block_validated_export(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    played = user_svc.get_or_create(tg_id=1, first_name="Алиса", last_name="Иванова")
    no_show = user_svc.get_or_create(tg_id=2, first_name="Сергей", last_name="Егоров")
    deck = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, played, deck, place=1)
    _participant(db, tournament, no_show, None, place=None)
    aetherhub = MagicMock()
    aetherhub.fetch_tournament.return_value = AetherhubTournamentData(
        url=tournament.aetherhub_url,
        players=[],
        rounds=[],
        standings=["Иванова Алиса"],
    )

    result = MagicOculusTournamentCollector(db, aetherhub).collect(tournament.id, validate_aetherhub=True)

    assert len(result.player_decks) == 1


def test_positional_text_uses_final_place_and_ignores_names(db, svc, user_svc, arch_svc):
    tournament = _tournament(svc, db)
    alice = user_svc.get_or_create(tg_id=1, username="alice", first_name="Алиса", last_name="Иванова")
    bob = user_svc.get_or_create(tg_id=2, username="bob", first_name="Боб", last_name="Петров")
    burn = arch_svc.get_or_create_by_name("Burn")
    elves = arch_svc.get_or_create_by_name("Elves")
    _participant(db, tournament, alice, burn, place=2)
    _participant(db, tournament, bob, elves, place=1)

    result = MagicOculusTournamentCollector(db).collect(tournament.id)

    assert result.positional_player_decks_text == "Elves\nBurn"


def test_positional_text_requires_complete_places():
    tournament = MagicOculusTournament(
        source_tournament_id=1,
        date=date(2026, 7, 24),
        club="Goldfish",
        aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/1",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves")],
    )

    with pytest.raises(MagicOculusCollectionError, match="места должны идти"):
        _ = tournament.positional_player_decks_text
