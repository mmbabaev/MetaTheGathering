from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.models import utc_now

DM_COOLDOWN_SECONDS = 3600


class PollService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_poll_for_tournament(self, tournament_id: int) -> models.TournamentPoll | None:
        return self.db.execute(
            select(models.TournamentPoll).where(models.TournamentPoll.tournament_id == tournament_id)
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
            select(models.TournamentPoll).where(models.TournamentPoll.tg_poll_id == tg_poll_id)
        ).scalar_one_or_none()

    def create_poll(
        self,
        tournament_id: int,
        chat_id: int,
        tg_poll_id: str,
        message_id: int,
        chat_username: str | None = None,
    ) -> models.TournamentPoll:
        poll = models.TournamentPoll(
            tournament_id=tournament_id,
            chat_id=chat_id,
            tg_poll_id=tg_poll_id,
            message_id=message_id,
            chat_username=chat_username,
        )
        self.db.add(poll)
        self.db.commit()
        self.db.refresh(poll)
        return poll

    def link_poll_to_tournament(self, poll_id: int, tournament_id: int) -> models.TournamentPoll:
        poll = self.db.get(models.TournamentPoll, poll_id)
        poll.tournament_id = tournament_id
        self.db.commit()
        self.db.refresh(poll)
        return poll

    def remove_vote(self, poll_id: int, tg_user_id: int) -> None:
        """Удаляет голос пользователя (когда он убрал выбор в опросе)."""
        existing = self.db.execute(
            select(models.PollVote).where(
                models.PollVote.poll_id == poll_id,
                models.PollVote.tg_user_id == tg_user_id,
            )
        ).scalar_one_or_none()
        if existing:
            self.db.delete(existing)
            self.db.commit()

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
            self.db.add(
                models.PollVote(
                    poll_id=poll_id,
                    tg_user_id=tg_user_id,
                    choice=choice,
                )
            )
        self.db.commit()

    def get_yes_voters_without_deck(self, tournament_id: int, poll_id: int | None = None) -> list[int]:
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
            )
            .scalars()
            .all()
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
            )
            .scalars()
            .all()
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
            )
            .scalars()
            .all()
        )

        return list(yes_voter_ids - registered_with_deck - recently_notified)

    def get_poll_stats(self, poll_id: int) -> tuple[int, int]:
        """Возвращает (yes_count, no_count) для опроса."""
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
            select(models.User.tg_id, models.User.username, models.User.first_name, models.User.last_name).where(
                models.User.tg_id.in_(tg_user_ids)
            )
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

    def get_poll_subscribers(self) -> list[int]:
        """tg_id пользователей, включивших опт-ин «уведомления о голосованиях» (реальные tg_id)."""
        return list(
            self.db.execute(
                select(models.User.tg_id).where(
                    models.User.notify_poll.is_(True),
                    models.User.tg_id > 0,
                )
            )
            .scalars()
            .all()
        )

    def mark_poll_notified(self, poll_id: int, tg_user_ids: list[int]) -> None:
        """Записывает, что боту разослал уведомление о голосовании этим tg_id (без дублей)."""
        if not tg_user_ids:
            return
        already = self.get_poll_notified_ids(poll_id)
        for tg_id in tg_user_ids:
            if tg_id in already:
                continue
            self.db.add(models.PollNotification(poll_id=poll_id, tg_user_id=tg_id))
            already.add(tg_id)
        self.db.commit()

    def get_poll_notified_ids(self, poll_id: int) -> set[int]:
        """tg_id, которым бот уже разослал уведомление об этом опросе."""
        return set(
            self.db.execute(
                select(models.PollNotification.tg_user_id).where(models.PollNotification.poll_id == poll_id)
            )
            .scalars()
            .all()
        )

    def get_poll_voter_ids(self, poll_id: int) -> set[int]:
        """tg_id всех, кто проголосовал в опросе (любой вариант)."""
        return set(
            self.db.execute(select(models.PollVote.tg_user_id).where(models.PollVote.poll_id == poll_id))
            .scalars()
            .all()
        )

    # --- Регуляры клуба и ping-список (issue #157, фаза 3) ---

    def list_club_chats(self) -> list[tuple[int, str]]:
        """(chat_id, метка) по каждому клубу, где есть турниры. Метка — название клуба или последнего турнира."""
        rows = self.db.execute(
            select(models.Tournament.chat_id, models.Tournament.club, models.Tournament.title).order_by(
                models.Tournament.created_at.desc()
            )
        ).all()
        seen: dict[int, str] = {}
        for chat_id, club, title in rows:
            if chat_id in seen:
                continue
            seen[chat_id] = club or title or f"chat {chat_id}"
        return list(seen.items())

    def get_club_players(self, chat_id: int) -> list[models.User]:
        """Реальные (tg_id>0) игроки, участвовавшие в турнирах клуба — кандидаты в регуляры."""
        return list(
            self.db.execute(
                select(models.User)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .join(models.Tournament, models.Tournament.id == models.Participant.tournament_id)
                .where(models.Tournament.chat_id == chat_id, models.User.tg_id > 0)
                .distinct()
                .order_by(models.User.first_name, models.User.last_name)
            )
            .scalars()
            .all()
        )

    def get_regular_user_ids(self, chat_id: int) -> set[int]:
        """Внутренние user.id регуляров клуба."""
        return set(
            self.db.execute(select(models.PollRegular.user_id).where(models.PollRegular.chat_id == chat_id))
            .scalars()
            .all()
        )

    def list_regulars(self, chat_id: int) -> list[models.User]:
        """Пользователи-регуляры клуба, отсортированные по имени."""
        return list(
            self.db.execute(
                select(models.User)
                .join(models.PollRegular, models.PollRegular.user_id == models.User.id)
                .where(models.PollRegular.chat_id == chat_id)
                .order_by(models.User.first_name, models.User.last_name)
            )
            .scalars()
            .all()
        )

    def toggle_regular(self, chat_id: int, user_id: int) -> bool:
        """Добавляет/убирает игрока из регуляров клуба. Возвращает новое состояние (True = регуляр)."""
        existing = self.db.execute(
            select(models.PollRegular).where(
                models.PollRegular.chat_id == chat_id,
                models.PollRegular.user_id == user_id,
            )
        ).scalar_one_or_none()
        if existing:
            self.db.delete(existing)
            self.db.commit()
            return False
        self.db.add(models.PollRegular(chat_id=chat_id, user_id=user_id))
        self.db.commit()
        return True

    def get_ping_targets(self, chat_id: int, poll_id: int | None) -> list[int]:
        """tg_id регуляров, кому «ещё написать»: регуляры МИНУС уведомлённые ботом МИНУС проголосовавшие.

        poll_id — опрос, по которому считаем «уже написали / уже проголосовали». None (опроса нет) →
        никого не исключаем, возвращаем всех регуляров.
        """
        regular_tg = set(
            self.db.execute(
                select(models.User.tg_id)
                .join(models.PollRegular, models.PollRegular.user_id == models.User.id)
                .where(models.PollRegular.chat_id == chat_id, models.User.tg_id > 0)
            )
            .scalars()
            .all()
        )
        if not regular_tg:
            return []
        exclude: set[int] = set()
        if poll_id is not None:
            exclude = self.get_poll_notified_ids(poll_id) | self.get_poll_voter_ids(poll_id)
        return sorted(regular_tg - exclude)

    def mark_notified(self, tournament_id: int, tg_user_ids: list[int]) -> None:
        """Записывает время последнего DM для участников турнира."""
        if not tg_user_ids:
            return
        now = utc_now()
        rows = (
            self.db.execute(
                select(models.Participant)
                .join(models.User, models.User.id == models.Participant.user_id)
                .where(
                    models.Participant.tournament_id == tournament_id,
                    models.User.tg_id.in_(tg_user_ids),
                )
            )
            .scalars()
            .all()
        )
        for p in rows:
            p.last_dm_at = now
        self.db.commit()
