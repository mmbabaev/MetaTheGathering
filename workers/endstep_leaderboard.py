"""Refresh the persisted Endstep RU leaderboard once and exit."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core.config import settings
from core.database import SessionLocal
from services.endstep import EndstepClient
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService

logger = logging.getLogger(__name__)


def refresh_once(db: Session, client: EndstepClient) -> EndstepRuLeaderboard:
    return EndstepRuLeaderboardService(db, client).refresh()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = SessionLocal()
    try:
        snapshot = refresh_once(db, EndstepClient(settings.ENDSTEP_API_URL))
    except Exception:
        db.rollback()
        logger.exception("Endstep RU leaderboard refresh failed; keeping the previous snapshot")
        return 1
    finally:
        db.close()

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
