from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.magicoculus import app
from services.magicoculus import (
    MagicOculusCollectionError,
    MagicOculusImportResult,
    MagicOculusPlayerDeck,
    MagicOculusTournament,
)


@contextmanager
def _db_context():
    yield MagicMock()


def test_preview_prints_json(monkeypatch):
    tournament = MagicOculusTournament(
        source_tournament_id=42,
        date=date(2026, 7, 24),
        club="Goldfish",
        aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/42",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves", final_place=1)],
    )
    monkeypatch.setattr("cli.magicoculus.get_db", _db_context)
    collector = MagicMock()
    collector.return_value.collect.return_value = tournament
    monkeypatch.setattr("cli.magicoculus.MagicOculusTournamentCollector", collector)

    result = CliRunner().invoke(app, ["preview", "42"])

    assert result.exit_code == 0
    assert '"sourceTournamentId": 42' in result.stdout
    assert '"playerDecksText": "Elves"' in result.stdout
    assert '"playerDecksNamedPreview": "Иванов Иван - Elves"' in result.stdout
    collector.return_value.collect.assert_called_once_with(42, validate_aetherhub=True)


def test_preview_reports_collection_error(monkeypatch):
    monkeypatch.setattr("cli.magicoculus.get_db", _db_context)
    collector = MagicMock()
    collector.return_value.collect.side_effect = MagicOculusCollectionError("нет колоды")
    monkeypatch.setattr("cli.magicoculus.MagicOculusTournamentCollector", collector)

    result = CliRunner().invoke(app, ["preview", "42"])

    assert result.exit_code == 1
    assert "Ошибка: нет колоды" in result.output


def test_send_requires_explicit_execute():
    result = CliRunner().invoke(app, ["send", "42"])

    assert result.exit_code == 2
    assert "--execute" in result.output


def test_send_uses_guarded_importer(monkeypatch):
    tournament = MagicOculusTournament(
        source_tournament_id=42,
        date=date(2026, 7, 24),
        club="Goldfish",
        aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/42",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves")],
    )
    monkeypatch.setattr("cli.magicoculus.get_db", _db_context)
    collector = MagicMock()
    collector.return_value.collect.return_value = tournament
    monkeypatch.setattr("cli.magicoculus.MagicOculusTournamentCollector", collector)
    importer = MagicMock()
    importer.return_value.import_once.return_value = MagicOculusImportResult(tournament_id=145, detail={})
    monkeypatch.setattr("cli.magicoculus.MagicOculusImporter", importer)
    monkeypatch.setattr("cli.magicoculus.MagicOculusClient", MagicMock())

    result = CliRunner().invoke(app, ["send", "42", "--execute"])

    assert result.exit_code == 0
    assert "#145" in result.output
    importer.return_value.import_once.assert_called_once_with(tournament, city="Москва")
