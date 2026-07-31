from datetime import date
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.migration import app
from services.datalens import DataLensTournament, TournamentPlayer

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
