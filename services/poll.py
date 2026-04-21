from __future__ import annotations

from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select

from core import models
from core.models import utc_now

DM_COOLDOWN_SECONDS = 3600


class PollService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_poll_for_tournament(self, tournament_id: int) -> models.TournamentPoll | None:
        return self.db.execute(
            select(models.TournamentPoll).where(
                models.TournamentPoll.tournament_id == tournament_id
            )
        ).scalar_one_or_none()

    def get_latest_poll_for_chat(self, chat_id: int) -> models.TournamentPoll | None:
        """Последний созданный опрос для данного chat_id."""
        return self.db.execute(
            select(models.TournamentPoll)
            .where(models.TournamentPoll.chat_id == chat_id)
            .order_by(models.TournamentPoll.created_at.desc())
            .limit(1)
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

    def get_yes_voters_without_deck(
        self, tournament_id: int, poll_id: int | None = None
    ) -> list[int]:
        """tg_user_ids who voted «пойду» (choice=0), have no archetype, and are not on DM cooldown.

        poll_id — если указан, голоса берутся из этого опроса (не обязательно привязанного
        к tournament_id). Колода и cooldown всегда проверяются по tournament_id.
        """
        if poll_id is None:
            poll = self.get_poll_for_tournament(tournament_id)
            if not poll:
                return []
            poll_id = poll.id

        yes_voter_ids = set(
            self.db.execute(
                select(models.PollVote.tg_user_id).where(
                    models.PollVote.poll_id == poll_id,
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

        cooldown_cutoff = utc_now() - timedelta(seconds=DM_COOLDOWN_SECONDS)
        recently_notified = set(
            self.db.execute(
                select(models.User.tg_id)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.last_dm_at.isnot(None),
                    models.Participant.last_dm_at > cooldown_cutoff,
                    models.User.tg_id.in_(yes_voter_ids),
                )
            ).scalars().all()
        )

        return list(yes_voter_ids - registered_with_deck - recently_notified)

    def get_poll_stats(self, poll_id: int) -> tuple[int, int]:
        """Возвращает (yes_count, no_count) для опроса."""
        from sqlalchemy import func
        rows = self.db.execute(
            select(models.PollVote.choice, func.count().label("cnt"))
            .where(models.PollVote.poll_id == poll_id)
            .group_by(models.PollVote.choice)
        ).all()
        stats = {r.choice: r.cnt for r in rows}
        return stats.get(0, 0), stats.get(1, 0)

    def get_voter_display_names(self, tg_user_ids: list[int]) -> dict[int, str]:
        """tg_id → отображаемое имя (username или first_name или id)."""
        if not tg_user_ids:
            return {}
        users = self.db.execute(
            select(models.User.tg_id, models.User.username,
                   models.User.first_name, models.User.last_name)
            .where(models.User.tg_id.in_(tg_user_ids))
        ).all()
        result = {}
        for u in users:
            parts = []
            if u.username:
                parts.append(f"@{u.username}")
            name = " ".join(filter(None, [u.first_name, u.last_name]))
            if name:
                parts.append(name)
            result[u.tg_id] = " ".join(parts) if parts else f"id{u.tg_id}"
        for tg_id in tg_user_ids:
            result.setdefault(tg_id, f"id{tg_id}")
        return result

    def mark_notified(self, tournament_id: int, tg_user_ids: list[int]) -> None:
        """Записывает время последнего DM для участников турнира."""
        if not tg_user_ids:
            return
        now = utc_now()
        rows = self.db.execute(
            select(models.Participant)
            .join(models.User, models.User.id == models.Participant.user_id)
            .where(
                models.Participant.tournament_id == tournament_id,
                models.User.tg_id.in_(tg_user_ids),
            )
        ).scalars().all()
        for p in rows:
            p.last_dm_at = now
        self.db.commit()
