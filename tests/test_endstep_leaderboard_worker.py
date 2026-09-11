from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from core.models import utc_now
from services.endstep_ru_leaderboard import EndstepRuLeaderboard
from workers.endstep_leaderboard import main, run_refresh


def _snapshot() -> EndstepRuLeaderboard:
    return EndstepRuLeaderboard(
        generated_at=datetime(2026, 9, 11),
        candidate_count=2,
        rows=(),
        missing_usernames=("Missing",),
        ambiguous_usernames=("Duplicate",),
    )


def test_worker_refreshes_once_and_closes_database():
    db = MagicMock()
    with (
        patch("workers.endstep_leaderboard.SessionLocal", return_value=db),
        patch("workers.endstep_leaderboard.EndstepClient") as client,
        patch("workers.endstep_leaderboard.refresh_once", return_value=_snapshot()) as refresh,
    ):
        exit_code = main()

    assert exit_code == 0
    refresh.assert_called_once_with(db, client.return_value)
    db.rollback.assert_not_called()
    db.close.assert_called_once_with()


def test_worker_rolls_back_and_fails_without_deleting_previous_snapshot():
    db = MagicMock()
    with (
        patch("workers.endstep_leaderboard.SessionLocal", return_value=db),
        patch("workers.endstep_leaderboard.EndstepClient"),
        patch("workers.endstep_leaderboard.refresh_once", side_effect=RuntimeError("temporary")),
    ):
        exit_code = main()

    assert exit_code == 1
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()


def test_startup_worker_skips_recent_snapshot():
    db = MagicMock()
    recent = _snapshot()
    recent = EndstepRuLeaderboard(
        generated_at=utc_now() - timedelta(hours=1),
        candidate_count=recent.candidate_count,
        rows=recent.rows,
        missing_usernames=recent.missing_usernames,
        ambiguous_usernames=recent.ambiguous_usernames,
    )
    with (
        patch("workers.endstep_leaderboard.SessionLocal", return_value=db),
        patch("workers.endstep_leaderboard.EndstepRuLeaderboardService") as service,
        patch("workers.endstep_leaderboard.EndstepClient") as client,
    ):
        service.return_value.latest.return_value = recent
        result = run_refresh(only_if_stale=True)

    assert result is None
    client.assert_not_called()
    service.return_value.refresh.assert_not_called()
    db.close.assert_called_once_with()


def test_startup_worker_refreshes_stale_snapshot():
    db = MagicMock()
    stale = EndstepRuLeaderboard(
        generated_at=utc_now() - timedelta(hours=13),
        candidate_count=2,
        rows=(),
        missing_usernames=(),
    )
    refreshed = _snapshot()
    with (
        patch("workers.endstep_leaderboard.SessionLocal", return_value=db),
        patch("workers.endstep_leaderboard.EndstepRuLeaderboardService") as service,
        patch("workers.endstep_leaderboard.EndstepClient") as client,
        patch("workers.endstep_leaderboard.refresh_once", return_value=refreshed) as refresh,
    ):
        service.return_value.latest.return_value = stale
        result = run_refresh(only_if_stale=True)

    assert result == refreshed
    refresh.assert_called_once_with(db, client.return_value)
    db.close.assert_called_once_with()
