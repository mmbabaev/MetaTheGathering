from datetime import date
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.migration import app
from services.datalens import DataLensTournament, DataLensTournamentError, TournamentPlayer

runner = CliRunner()


def test_datalens_command_outputs_full_tournament(monkeypatch):
    service = MagicMock()
    service.tournament.return_value = DataLensTournament(
        date=date(2026, 7, 20),
        club="Единорог",
        players=[TournamentPlayer(place=1, player="Игрок", deck="White Heroic")],
    )
    monkeypatch.setattr("cli.migration.DataLensService", lambda: service)

    result = runner.invoke(app, ["datalens", "2026-07-20", "--club", "Единорог"])

    assert result.exit_code == 0
    assert '"deck": "White Heroic"' in result.stdout
    service.tournament.assert_called_once_with(date(2026, 7, 20), club="Единорог")


def test_aetherhub_command_outputs_only_url(monkeypatch):
    service = MagicMock()
    service.find_tournament_url.return_value = "https://aetherhub.com/Tourney/RoundTourney/100624"
    monkeypatch.setattr("cli.migration.AetherhubService", lambda: service)

    result = runner.invoke(app, ["aetherhub", "2026-07-20", "--club", "Единорог"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "https://aetherhub.com/Tourney/RoundTourney/100624"
    service.find_tournament_url.assert_called_once_with(
        "https://aetherhub.com/User/Edinorog/", date(2026, 7, 20), "Pauper"
    )


def test_aetherhub_command_fails_when_tournament_missing(monkeypatch):
    service = MagicMock()
    service.find_tournament_url.return_value = None
    monkeypatch.setattr("cli.migration.AetherhubService", lambda: service)

    result = runner.invoke(app, ["aetherhub", "2026-07-20", "--club", "Goldfish"])

    assert result.exit_code == 1
    assert "не найден" in result.stderr


def test_datalens_command_reports_collection_error(monkeypatch):
    service = MagicMock()
    service.tournament.side_effect = DataLensTournamentError("сломался чарт")
    monkeypatch.setattr("cli.migration.DataLensService", lambda: service)

    result = runner.invoke(app, ["datalens", "2026-07-20", "--club", "Единорог"])

    assert result.exit_code == 1
    assert "сломался чарт" in result.stderr


def test_aetherhub_command_rejects_unknown_club():
    result = runner.invoke(app, ["aetherhub", "2026-07-20", "--club", "Unknown"])

    assert result.exit_code == 2
    assert "Неизвестный клуб" in result.stderr


def test_aetherhub_command_reports_format_error(monkeypatch):
    service = MagicMock()
    service.find_tournament_url.side_effect = ValueError("Unsupported format")
    monkeypatch.setattr("cli.migration.AetherhubService", lambda: service)

    result = runner.invoke(app, ["aetherhub", "2026-07-20", "--club", "Goldfish", "--format", "Modern"])

    assert result.exit_code == 1
    assert "Unsupported format" in result.stderr
