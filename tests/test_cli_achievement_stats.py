from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.achievements import app
from services.season_stats import SeasonStatsQuality, SeasonStatsSnapshot


def _empty_snapshot() -> SeasonStatsSnapshot:
    return SeasonStatsSnapshot(
        as_of=datetime(2026, 9, 1),
        club=None,
        history_days=365,
        deck_window_days=120,
        winrate_window_days=90,
        min_h2h_matches=3,
        min_window_matches=5,
        quality=SeasonStatsQuality(
            tournaments_scanned=0,
            complete_tournaments=0,
            excluded_not_closed=0,
            excluded_incomplete=0,
            pairing_rows=0,
            scored_matches=0,
            matched_player_rows=0,
            unmatched_player_rows=0,
            actual_participations=0,
            registered_participations=0,
            participants_without_pairing=0,
        ),
        popular_decks=[],
        players=[],
    )


def test_season_stats_command_outputs_machine_readable_json(monkeypatch):
    service = MagicMock()
    service.build_snapshot.return_value = _empty_snapshot()

    @contextmanager
    def fake_get_db():
        yield object()

    monkeypatch.setattr("cli.achievements.get_db", fake_get_db)
    monkeypatch.setattr("cli.achievements.SeasonStatsService", lambda db: service)

    result = CliRunner().invoke(app, ["season-stats", "--as-of", "2026-09-01", "--format", "json"])

    assert result.exit_code == 0
    assert '"as_of": "2026-09-01T00:00:00"' in result.stdout
    service.build_snapshot.assert_called_once()
    assert service.build_snapshot.call_args.kwargs["deck_window_days"] == 120


def test_season_stats_command_rejects_unknown_format():
    result = CliRunner().invoke(app, ["season-stats", "--as-of", "2026-09-01", "--format", "csv"])

    assert result.exit_code == 2
    assert "markdown или json" in result.stderr
