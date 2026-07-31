from datetime import date
from unittest.mock import MagicMock

import requests

from services.aetherhub_models import AetherhubTournamentData
from services.datalens import (
    DataLensTournament,
    DataLensTournamentBatch,
    DataLensTournamentIssue,
    TournamentPlayer,
)
from services.magicoculus import MagicOculusFeedback, MagicOculusImportResult
from services.tournament_migration import HistoricalTournamentMigrator


def _tournament(event_date, club, players=1):
    return DataLensTournament(
        date=event_date,
        club=club,
        players=[TournamentPlayer(place=i, player=f"Player {i}", deck=f"Deck {i}") for i in range(1, players + 1)],
    )


def _migrator(batch, indexes, existing=None, fetched=None):
    datalens = MagicMock()
    datalens.all_tournaments.return_value = batch
    aetherhub = MagicMock()

    def index_for(club_url, tournament_format):
        owner = club_url.rstrip("/").rsplit("/", 1)[-1]
        return next((value for key, value in indexes.items() if key.casefold() == owner.casefold()), {})

    aetherhub.tournament_urls_by_date.side_effect = index_for
    fetcher = MagicMock()
    fetched = fetched or {}
    fetcher.fetch_tournament.side_effect = lambda url: fetched[url]
    oculus = MagicMock()
    oculus.existing_daily_keys.return_value = existing or {}
    return HistoricalTournamentMigrator(
        datalens,
        aetherhub,
        oculus,
        aetherhub_factory=lambda: fetcher,
    ), oculus


def _source(count):
    return AetherhubTournamentData(url="url", players=[], rounds=[], standings=[f"P{i}" for i in range(count)])


def _url(number):
    return f"https://aetherhub.com/Tourney/RoundTourney/{number}"


def test_dry_run_isolates_invalid_missing_ambiguous_mismatch_and_ready():
    ready = _tournament(date(2026, 7, 20), "Единорог", 2)
    missing = _tournament(date(2026, 7, 10), "Единорог")
    ambiguous = _tournament(date(2026, 7, 22), "Единорог")
    mismatch = _tournament(date(2026, 7, 23), "Единорог", 2)
    existing = _tournament(date(2026, 7, 24), "Goldfish")
    batch = DataLensTournamentBatch(
        tournaments=[ready, missing, ambiguous, mismatch, existing],
        issues=[DataLensTournamentIssue(date=date(2025, 9, 1), club="Единорог", message="bad places")],
    )
    indexes = {
        "Edinorog": {
            ready.date: [_url(1)],
            ambiguous.date: [_url(2), _url(3)],
            mismatch.date: [_url(4)],
        },
        "Goldfish": {},
    }
    migrator, oculus = _migrator(
        batch,
        indexes,
        existing={(existing.date, "goldfish", "pauper"): 77},
        fetched={
            _url(1): _source(2),
            _url(2): _source(1),
            _url(3): _source(1),
            _url(4): _source(1),
        },
    )

    report = migrator.run(execute=False)

    assert report.counts() == {
        "invalid_datalens": 1,
        "ready": 2,
        "missing_aetherhub": 1,
        "ambiguous_aetherhub": 1,
        "already_exists": 1,
    }
    oculus.import_tournament.assert_not_called()


def test_execute_imports_positional_payload_and_caches_references():
    first = _tournament(date(2026, 7, 20), "Единорог", 2)
    second = _tournament(date(2026, 7, 27), "Единорог", 1)
    batch = DataLensTournamentBatch(tournaments=[first, second], issues=[])
    indexes = {"Edinorog": {first.date: [_url(1)], second.date: [_url(2)]}, "Goldfish": {}}
    migrator, oculus = _migrator(
        batch,
        indexes,
        fetched={_url(1): _source(2), _url(2): _source(1)},
    )
    oculus.resolve_reference_ids.return_value = ("moscow", "edinorog_moscow", "pauper")
    oculus.import_tournament.side_effect = [
        MagicOculusImportResult(
            tournament_id=101,
            warnings=[MagicOculusFeedback(code="POSITIONAL", message="used")],
            detail={},
        ),
        MagicOculusImportResult(tournament_id=102, detail={}),
    ]

    report = migrator.run(execute=True)

    assert report.counts() == {"imported": 2}
    assert oculus.resolve_reference_ids.call_count == 1
    payload = oculus.import_tournament.call_args_list[0].args[0]
    assert payload.source_tournament_id is None
    assert payload.positional_player_decks_text == "Deck 1\nDeck 2"
    assert report.items[0].warnings == ["POSITIONAL: used"]


def test_event_oculus_error_does_not_abort_following_event():
    first = _tournament(date(2026, 7, 20), "Единорог")
    second = _tournament(date(2026, 7, 27), "Единорог")
    batch = DataLensTournamentBatch(tournaments=[first, second], issues=[])
    indexes = {"Edinorog": {first.date: [_url(1)], second.date: [_url(2)]}, "Goldfish": {}}
    migrator, oculus = _migrator(batch, indexes, fetched={_url(1): _source(1), _url(2): _source(1)})
    oculus.resolve_reference_ids.return_value = ("city", "club", "format")
    oculus.import_tournament.side_effect = [
        ValueError("bad event"),
        MagicOculusImportResult(tournament_id=2, detail={}),
    ]

    report = migrator.run(execute=True)

    assert report.counts() == {"oculus_error": 1, "imported": 1}


def test_repeated_system_errors_abort_remaining_events():
    tournaments = [_tournament(date(2026, 7, day), "Единорог") for day in (20, 21, 22, 23)]
    batch = DataLensTournamentBatch(tournaments=tournaments, issues=[])
    indexes = {"Edinorog": {row.date: [_url(row.date.day)] for row in tournaments}, "Goldfish": {}}
    fetched = {_url(row.date.day): _source(1) for row in tournaments}
    migrator, oculus = _migrator(batch, indexes, fetched=fetched)
    oculus.resolve_reference_ids.return_value = ("city", "club", "format")
    oculus.import_tournament.side_effect = requests.ConnectionError("down")

    report = migrator.run(execute=True, max_consecutive_system_errors=2)

    assert report.counts() == {"oculus_error": 2, "aborted": 2}
    assert oculus.import_tournament.call_count == 2


def test_aetherhub_fetch_error_is_reported():
    tournament = _tournament(date(2026, 7, 20), "Единорог")
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    migrator, _ = _migrator(batch, {"Edinorog": {tournament.date: [_url(1)]}, "Goldfish": {}})

    report = migrator.run(execute=False)

    assert report.counts() == {"aetherhub_error": 1}


def test_adjacent_date_candidate_is_selected_only_by_exact_roster():
    tournament = _tournament(date(2026, 5, 28), "Goldfish", 16)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {
        "Edinorog": {},
        "Goldfish": {date(2026, 5, 29): [_url(1), _url(2)]},
    }
    migrator, _ = _migrator(
        batch,
        indexes,
        fetched={_url(1): _source(9), _url(2): _source(16)},
    )

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(2)
    assert report.items[0].warnings == [
        "AETHERHUB_ADJACENT_DATE: URL найден на соседней API-дате и подтверждён точным roster"
    ]


def test_adjacent_date_candidate_with_wrong_roster_is_not_selected():
    tournament = _tournament(date(2026, 6, 18), "Goldfish", 15)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {"Edinorog": {}, "Goldfish": {date(2026, 6, 19): [_url(1)]}}
    migrator, _ = _migrator(batch, indexes, fetched={_url(1): _source(16)})

    report = migrator.run(execute=False)

    assert report.counts() == {"roster_mismatch": 1}


def test_unique_exact_date_url_is_kept_when_aetherhub_roster_is_incomplete():
    tournament = _tournament(date(2023, 8, 14), "Единорог", 27)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {"Rog": {tournament.date: [_url(22587)]}}
    migrator, _ = _migrator(batch, indexes, fetched={_url(22587): _source(28)})

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(22587)
    assert report.items[0].warnings == [
        "AETHERHUB_ROSTER_MISMATCH_IGNORED: точный URL выбран по клубу, формату и дате; DataLens=27, AetherHub=28"
    ]


def test_multiple_same_date_candidates_are_disambiguated_by_roster():
    tournament = _tournament(date(2026, 3, 19), "Goldfish", 14)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {"Edinorog": {}, "Goldfish": {tournament.date: [_url(1), _url(2)]}}
    migrator, _ = _migrator(
        batch,
        indexes,
        fetched={_url(1): _source(16), _url(2): _source(14)},
    )

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(2)
    assert report.items[0].warnings == [
        "AETHERHUB_ROSTER_DISAMBIGUATED: URL выбран из нескольких кандидатов по точному roster"
    ]


def test_legacy_organizer_history_is_used_for_old_tournament():
    tournament = _tournament(date(2024, 10, 28), "Единорог", 15)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {"Rog": {tournament.date: [_url(34441)]}}
    migrator, _ = _migrator(batch, indexes, fetched={_url(34441): _source(15)})

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(34441)


def test_verified_one_off_tournament_url_is_used():
    tournament = _tournament(date(2025, 3, 22), "Единорог", 10)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    migrator, _ = _migrator(batch, {}, fetched={_url(37996): _source(10)})

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(37996)
    assert report.items[0].warnings == [
        "AETHERHUB_VERIFIED_OVERRIDE: URL подтверждён ручной сверкой публичного каталога и DataLens"
    ]


def test_verified_override_resolves_ambiguous_date_and_incomplete_roster():
    tournament = _tournament(date(2026, 3, 26), "Goldfish", 14)
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    indexes = {"Goldfish": {tournament.date: [_url(98477), _url(98476)]}}
    migrator, _ = _migrator(batch, indexes, fetched={_url(98477): _source(15)})

    report = migrator.run(execute=False)

    assert report.counts() == {"ready": 1}
    assert report.items[0].aetherhub_url == _url(98477)
    assert report.items[0].warnings == [
        "AETHERHUB_VERIFIED_OVERRIDE: URL подтверждён ручной сверкой публичного каталога и DataLens",
        "AETHERHUB_ROSTER_MISMATCH_IGNORED: точный URL выбран по клубу, формату и дате; DataLens=14, AetherHub=15",
    ]


def test_callback_receives_checkpoint_updates():
    tournament = _tournament(date(2026, 7, 20), "Единорог")
    batch = DataLensTournamentBatch(tournaments=[tournament], issues=[])
    migrator, _ = _migrator(batch, {"Edinorog": {}, "Goldfish": {}})
    callback = MagicMock()

    report = migrator.run(execute=False, on_update=callback)

    assert callback.call_count == 2
    assert callback.call_args.args[0] is report
