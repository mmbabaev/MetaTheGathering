"""Refresh the persisted Endstep RU leaderboard once and exit."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from core.config import settings
from core.database import SessionLocal
from core.models import utc_now
from services.endstep import EndstepClient
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService

logger = logging.getLogger(__name__)

STARTUP_MAX_SNAPSHOT_AGE = timedelta(hours=12)


def refresh_once(db: Session, client: EndstepClient) -> EndstepRuLeaderboard:
    return EndstepRuLeaderboardService(db, client).refresh()


def run_refresh(*, only_if_stale: bool = False) -> EndstepRuLeaderboard | None:
    """Refresh using an isolated DB session; optionally recover only a missed run."""

    db = SessionLocal()
    try:
        if only_if_stale:
            latest = EndstepRuLeaderboardService(db).latest()
            if latest is not None and latest.generated_at >= utc_now() - STARTUP_MAX_SNAPSHOT_AGE:
                return None
        return refresh_once(db, EndstepClient(settings.ENDSTEP_API_URL))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        snapshot = run_refresh()
    except Exception:
        logger.exception("Endstep RU leaderboard refresh failed; keeping the previous snapshot")
        return 1

    if snapshot is None:  # pragma: no cover - only_if_stale is not used by the CLI
        return 0

    logger.info(
        "Endstep RU leaderboard refreshed: candidates=%s, found=%s, missing=%s, ambiguous=%s",
        snapshot.candidate_count,
        len(snapshot.rows),
        len(snapshot.missing_usernames),
        len(snapshot.ambiguous_usernames),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
