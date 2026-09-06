import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from core import models
from core.schemas import TournamentCreate
from services.magicoculus import (
    MagicOculusApiError,
    MagicOculusFeedback,
    MagicOculusImporter,
    MagicOculusImportResult,
    MagicOculusPlayerDeck,
    MagicOculusTournament,
)


def _payload(source_id):
    return MagicOculusTournament(
        source_tournament_id=source_id,
        date=date(2026, 7, 24),
        club="Goldfish",
        aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/42",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves")],
    )


def _swiss_payload(source_id):
    return MagicOculusTournament(
        source_tournament_id=source_id,
        date=date(2026, 9, 5),
        club="Endstep-ru",
        final_standings_csv="Rank,Name,Points\r\n1,Иванов Иван,3\r\n",
        all_rounds_csv="Table,Player 1,Player 2,Match Results\r\n1,Иванов Иван,BYE,2 - 0\r\n",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves", final_place=1)],
    )


def test_records_success_and_warnings(db, svc):
    tournament = svc.create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    client = MagicMock()
    client.resolve_reference_ids.return_value = ("moscow", "goldfish_moscow", "pauper")
    client.import_tournament.return_value = MagicOculusImportResult(
        tournament_id=145,
        warnings=[MagicOculusFeedback(code="NORMALIZED", message="Исправлено")],
        detail={"id": 145},
    )

    result = MagicOculusImporter(db, client).import_once(_payload(tournament.id), city="Москва")

    assert result.tournament_id == 145
    row = db.query(models.MagicOculusImport).one()
    assert row.status == "imported"
    assert row.magicoculus_tournament_id == 145
    assert json.loads(row.warnings_json)[0]["code"] == "NORMALIZED"
    assert row.imported_at is not None


def test_failure_is_recorded_and_not_automatically_retried(db, svc):
    tournament = svc.create_tournament(TournamentCreate(title="Pauper", chat_id=1))
    client = MagicMock()
    client.resolve_reference_ids.return_value = ("moscow", "goldfish_moscow", "pauper")
    client.import_tournament.side_effect = TimeoutError("unknown outcome")
    importer = MagicOculusImporter(db, client)
    payload = _payload(tournament.id)

    with pytest.raises(TimeoutError, match="unknown outcome"):
        importer.import_once(payload, city="Москва")

    row = db.query(models.MagicOculusImport).one()
    assert row.status == "error"
    assert json.loads(row.error_json)["type"] == "TimeoutError"

    with pytest.raises(MagicOculusApiError, match="автоматический повтор запрещён"):
        importer.import_once(payload, city="Москва")
    assert client.import_tournament.call_count == 1


def test_internal_swiss_journal_uses_tournament_id_without_fake_aetherhub_url(db, svc):
    tournament = svc.create_tournament(TournamentCreate(title="Endstep Swiss", chat_id=1))
    client = MagicMock()
    client.resolve_reference_ids.return_value = ("endstep", "Endstep-Ru", "pauper")
    client.import_tournament.return_value = MagicOculusImportResult(
        tournament_id=470,
        warnings=[],
        detail={"id": 470},
    )
    payload = _swiss_payload(tournament.id)
    importer = MagicOculusImporter(db, client)

    result = importer.import_once(payload, city="Endstep")

    assert result.tournament_id == 470
    journal = db.query(models.MagicOculusImport).one()
    assert journal.tournament_id == tournament.id
    assert journal.aetherhub_url is None
    with pytest.raises(MagicOculusApiError, match="автоматический повтор запрещён"):
        importer.import_once(payload, city="Endstep")
    assert client.import_tournament.call_count == 1
