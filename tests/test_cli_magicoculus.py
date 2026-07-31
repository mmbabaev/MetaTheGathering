from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.magicoculus import app
from services.magicoculus import MagicOculusCollectionError, MagicOculusPlayerDeck, MagicOculusTournament


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

    result = CliRunner().invoke(app, ["42"])

    assert result.exit_code == 0
    assert '"sourceTournamentId": 42' in result.stdout
    assert '"playerDecksText": "Иванов Иван - Elves"' in result.stdout


def test_preview_reports_collection_error(monkeypatch):
    monkeypatch.setattr("cli.magicoculus.get_db", _db_context)
    collector = MagicMock()
    collector.return_value.collect.side_effect = MagicOculusCollectionError("нет колоды")
    monkeypatch.setattr("cli.magicoculus.MagicOculusTournamentCollector", collector)

    result = CliRunner().invoke(app, ["42"])

    assert result.exit_code == 1
    assert "Ошибка: нет колоды" in result.output
