from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.endstep import app
from services.endstep import EndstepApiError, EndstepLeaderboardPlayer, EndstepPlayerLookup


def _ranked_player() -> EndstepLeaderboardPlayer:
    return EndstepLeaderboardPlayer(
        userId="user-1",
        username="PlayerOne",
        rank=17,
        rating=1588,
        rd=82,
        wins=11,
        losses=7,
        draws=2,
        matchesPlayed=20,
    )


def test_find_prints_ranked_and_missing_players(monkeypatch):
    client = MagicMock()
    client.find_players.return_value = (
        EndstepPlayerLookup(requested_username="PlayerOne", player=_ranked_player()),
        EndstepPlayerLookup(requested_username="Missing", player=None),
    )
    client_class = MagicMock(return_value=client)
    monkeypatch.setattr("cli.endstep.EndstepClient", client_class)

    result = CliRunner().invoke(app, ["PlayerOne", "Missing"])

    assert result.exit_code == 0
    assert "#17 PlayerOne — 1588 ±82 · 11–7–2" in result.output
    assert "— Missing: не найден" in result.output
    client.find_players.assert_called_once_with(["PlayerOne", "Missing"], format_name="Pauper", season_id=None)


def test_find_reports_safe_api_error(monkeypatch):
    client = MagicMock()
    client.find_players.side_effect = EndstepApiError("Endstep временно недоступен")
    monkeypatch.setattr("cli.endstep.EndstepClient", MagicMock(return_value=client))

    result = CliRunner().invoke(app, ["PlayerOne"])

    assert result.exit_code == 1
    assert "Ошибка: Endstep временно недоступен" in result.output
