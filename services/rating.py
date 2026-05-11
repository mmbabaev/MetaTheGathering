from sqlalchemy import func
from sqlalchemy.orm import Session

from core.models import Participant, User


class RatingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_decks_added_by(self, tg_id: int) -> int:
        """Count how many participant decks this user has recorded."""
        return self.db.query(func.count(Participant.id)).filter(Participant.deck_added_by_tg_id == tg_id).scalar() or 0

    def top_deck_contributors(self, limit: int = 10) -> list[tuple[User, int]]:
        """Return top N users who recorded the most decks, ordered by count DESC."""
        rows = (
            self.db.query(User, func.count(Participant.id).label("cnt"))
            .join(Participant, Participant.deck_added_by_tg_id == User.tg_id)
            .filter(Participant.deck_added_by_tg_id.isnot(None))
            .group_by(User.id)
            .order_by(func.count(Participant.id).desc())
            .limit(limit)
            .all()
        )
        return [(user, cnt) for user, cnt in rows]
