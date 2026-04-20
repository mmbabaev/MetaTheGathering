from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from core import models


class PollService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_poll_for_tournament(self, tournament_id: int) -> models.TournamentPoll | None:
        return self.db.execute(
            select(models.TournamentPoll).where(
                models.TournamentPoll.tournament_id == tournament_id
            )
        ).scalar_one_or_none()

    def get_poll_by_tg_id(self, tg_poll_id: str) -> models.TournamentPoll | None:
        return self.db.execute(
            select(models.TournamentPoll).where(
                models.TournamentPoll.tg_poll_id == tg_poll_id
            )
        ).scalar_one_or_none()

    def create_poll(
        self,
        tournament_id: int,
        chat_id: int,
        tg_poll_id: str,
        message_id: int,
    ) -> models.TournamentPoll:
        poll = models.TournamentPoll(
            tournament_id=tournament_id,
            chat_id=chat_id,
            tg_poll_id=tg_poll_id,
            message_id=message_id,
        )
        self.db.add(poll)
        self.db.commit()
        self.db.refresh(poll)
        return poll

    def upsert_vote(self, poll_id: int, tg_user_id: int, choice: int) -> None:
        existing = self.db.execute(
            select(models.PollVote).where(
                models.PollVote.poll_id == poll_id,
                models.PollVote.tg_user_id == tg_user_id,
            )
        ).scalar_one_or_none()
        if existing:
            existing.choice = choice
        else:
            self.db.add(models.PollVote(
                poll_id=poll_id,
                tg_user_id=tg_user_id,
                choice=choice,
            ))
        self.db.commit()

    def get_yes_voters_without_deck(self, tournament_id: int) -> list[int]:
        """tg_user_ids who voted «пойду» (choice=0) but have no archetype in the tournament."""
        poll = self.get_poll_for_tournament(tournament_id)
        if not poll:
            return []

        yes_voter_ids = set(
            self.db.execute(
                select(models.PollVote.tg_user_id).where(
                    models.PollVote.poll_id == poll.id,
                    models.PollVote.choice == 0,
                )
            ).scalars().all()
        )
        if not yes_voter_ids:
            return []

        registered_with_deck = set(
            self.db.execute(
                select(models.User.tg_id)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.archetype_id.isnot(None),
                    models.User.tg_id.in_(yes_voter_ids),
                )
            ).scalars().all()
        )

        return list(yes_voter_ids - registered_with_deck)
