from unittest.mock import MagicMock

from bot.scheduler import EndstepLeaderboardRefreshJob

from .test_endstep_leaderboard_worker import _snapshot


async def test_scheduler_job_runs_worker_with_requested_staleness_mode():
    refresh = MagicMock(return_value=_snapshot())

    result = await EndstepLeaderboardRefreshJob(refresh).run(only_if_stale=True)

    assert result == _snapshot()
    refresh.assert_called_once_with(only_if_stale=True)


async def test_scheduler_job_keeps_previous_snapshot_on_failure():
    refresh = MagicMock(side_effect=RuntimeError("Endstep unavailable"))

    result = await EndstepLeaderboardRefreshJob(refresh).run()

    assert result is None
    refresh.assert_called_once_with(only_if_stale=False)
