"""История игрока для правил ачивок — с кэшами на один прогон.

Правила спрашивают историю много раз и для многих игроков сразу, поэтому доступ к БД
собран здесь: имена → аккаунты, паринги по турнирам и участия игроков кэшируются на
время жизни объекта. Объект живёт один прогон (оценка одного турнира или один шаг
бэкафилла) и переиспользуется всеми правилами.

Все счётчики — производные: они пересчитываются из первичных данных, а не накапливаются.
Поэтому повторная оценка турнира даёт те же значения (см. docs/achievements.md §4.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.user import UserService

MULTICLASS_WINDOW_DAYS = 90


@dataclass(frozen=True)
class Participation:
    """Участие игрока в турнире, засчитанное для ачивок (колоду записал он сам)."""

    tournament_id: int
    club: Optional[str]
    played_at: datetime
    archetype_name: Optional[str]
    deck_key: Optional[str]  # general_name или name — «одна и та же дека»


@dataclass(frozen=True)
class PlayerRecord:
    """Результат игрока в турнире по парингам."""

    wins: int
    losses: int
    draws: int
    rounds: int

    @property
    def record(self) -> str:
        base = f"{self.wins}-{self.losses}"
        return f"{base}-{self.draws}" if self.draws else base


@dataclass(frozen=True)
class AchievementMatch:
    """Read-only canonical match row used by achievement calculations."""

    id: int
    tournament_id: int
    round_number: int
    player_name: str
    player_user_id: Optional[int]
    opponent_name: Optional[str]
    player_wins: Optional[int]
    opponent_wins: Optional[int]

    @property
    def is_bye(self) -> bool:
        return self.opponent_name is None

    @property
    def is_complete(self) -> bool:
        return self.is_bye or (self.player_wins is not None and self.opponent_wins is not None)


def counts_for_achievements(participant: models.Participant, user: models.User) -> bool:
    """Гейт зачёта: турнир идёт в прогресс, только если игрок сам записал свою колоду.

    Записал админ или оппонент — не в зачёт (docs/achievements.md §2.5). Единственное
    исключение — «Метаписец», который награждает как раз запись чужих колод.
    """
    return (
        participant.archetype_id is not None
        and not participant.added_by_admin
        and participant.deck_added_by_tg_id == user.tg_id
    )


def tournament_date(tournament: models.Tournament) -> datetime:
    """Дата турнира: старт игры, иначе момент создания."""
    return tournament.started_at or tournament.created_at


class AchievementHistory:
    """Исторические данные игроков с кэшированием на прогон."""

    def __init__(self, db: Session, users: Optional[UserService] = None) -> None:
        self.db = db
        self._users = users if users is not None else UserService(db)
        self._user_by_name: dict[str, Optional[models.User]] = {}
        self._pairings: dict[int, list[models.RoundPairing]] = {}
        self._matches: dict[int, list[AchievementMatch]] = {}
        self._participations: dict[int, list[Participation]] = {}
        self._first_recorder: dict[int, Optional[int]] = {}

    # ------------------------------------------------------------------ имена

    def user_by_name(self, name: str) -> Optional[models.User]:
        """Имя из парингов → аккаунт без merge/create и любых других writes."""
        if name not in self._user_by_name:
            normalized = re.sub(r"\(\s*\d+\s*points?\s*\)", "", name or "", flags=re.IGNORECASE)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            self._user_by_name[name] = self._users.find_by_name(normalized) if normalized else None
        return self._user_by_name[name]

    def user_ids_by_name(self, tournament_id: int) -> dict[str, int]:
        """{имя из парингов: user_id} для одного турнира; несматченные имена пропущены."""
        result: dict[str, int] = {}
        for pairing in self.pairings(tournament_id):
            user = self.user_by_name(pairing.player_name)
            if user is not None:
                result[pairing.player_name] = user.id
        return result

    # --------------------------------------------------------------- паринги

    def pairings(self, tournament_id: int) -> list[models.RoundPairing]:
        if tournament_id not in self._pairings:
            rows = (
                self.db.execute(select(models.RoundPairing).where(models.RoundPairing.tournament_id == tournament_id))
                .scalars()
                .all()
            )
            self._pairings[tournament_id] = list(rows)
        return self._pairings[tournament_id]

    def matches(self, tournament_id: int) -> list[AchievementMatch]:
        """Canonical immutable projection over imported pairing rows."""
        if tournament_id not in self._matches:
            self._matches[tournament_id] = [
                AchievementMatch(
                    id=pairing.id,
                    tournament_id=pairing.tournament_id,
                    round_number=pairing.round_number,
                    player_name=pairing.player_name,
                    player_user_id=(user.id if (user := self.user_by_name(pairing.player_name)) else None),
                    opponent_name=pairing.opponent_name,
                    player_wins=pairing.player_wins,
                    opponent_wins=pairing.opponent_wins,
                )
                for pairing in self.pairings(tournament_id)
            ]
        return self._matches[tournament_id]

    def is_closed(self, tournament_id: int) -> bool:
        tournament = self.db.get(models.Tournament, tournament_id)
        return bool(tournament and tournament.status == models.TournamentStatus.CLOSED)

    def is_complete(self, tournament_id: int) -> bool:
        """Все не-бай матчи турнира имеют счёт. Пустой турнир не считается завершённым."""
        matches = self.matches(tournament_id)
        if not matches:
            return False
        return all(match.is_complete for match in matches)

    def actually_played(self, tournament_id: int, user_id: int) -> bool:
        return any(match.player_user_id == user_id for match in self.matches(tournament_id))

    def tournament_is_eligible(self, tournament_id: int) -> bool:
        return self.is_closed(tournament_id) and self.is_complete(tournament_id)

    def record_for(self, tournament_id: int, user_id: int) -> Optional[PlayerRecord]:
        """Результат игрока в турнире. None — игрока нет в парингах."""
        matches = [match for match in self.matches(tournament_id) if match.player_user_id == user_id]
        if not matches:
            return None
        wins = losses = draws = rounds = 0
        for pairing in matches:
            rounds += 1
            if pairing.opponent_name is None:
                wins += 1  # бай — победа (так же считает отбивка «сбор завершён»)
            elif pairing.player_wins is None or pairing.opponent_wins is None:
                continue
            elif pairing.player_wins > pairing.opponent_wins:
                wins += 1
            elif pairing.player_wins < pairing.opponent_wins:
                losses += 1
            else:
                draws += 1
        return PlayerRecord(wins=wins, losses=losses, draws=draws, rounds=rounds)

    def total_rounds(self, tournament_id: int) -> int:
        pairings = self.matches(tournament_id)
        return max((p.round_number for p in pairings), default=0)

    def is_undefeated(self, tournament_id: int, user_id: int) -> bool:
        """X-0: сыграл все раунды, все победы, ни поражений, ни ничьих."""
        record = self.record_for(tournament_id, user_id)
        total = self.total_rounds(tournament_id)
        if record is None or total == 0:
            return False
        return record.losses == 0 and record.draws == 0 and record.rounds == total and record.wins == total

    # ------------------------------------------------------------- участия

    def participations(self, user_id: int, *, until: Optional[datetime] = None) -> list[Participation]:
        """Засчитанные участия игрока по возрастанию даты (гейт §2.5 уже применён).

        ``until`` отсекает турниры позже указанной даты. Это важно для бэкафилла: оценивая
        турнир от 3 марта, правило должно видеть только то, что игрок успел к 3 марта, иначе
        «Завсегдатай III» выдался бы задним числом в самом первом турнире истории.
        """
        items = self._all_participations(user_id)
        if until is None:
            return items
        return [p for p in items if p.played_at <= until]

    def _all_participations(self, user_id: int) -> list[Participation]:
        if user_id in self._participations:
            return self._participations[user_id]

        user = self.db.get(models.User, user_id)
        if user is None:
            self._participations[user_id] = []
            return []

        rows = self.db.execute(
            select(models.Participant, models.Tournament, models.Archetype)
            .join(models.Tournament, models.Participant.tournament_id == models.Tournament.id)
            .outerjoin(models.Archetype, models.Participant.archetype_id == models.Archetype.id)
            .where(models.Participant.user_id == user_id)
        ).all()
        items = [
            Participation(
                tournament_id=tournament.id,
                club=tournament.club,
                played_at=tournament_date(tournament),
                archetype_name=archetype.name if archetype is not None else None,
                deck_key=(archetype.general_name or archetype.name) if archetype is not None else None,
            )
            for participant, tournament, archetype in rows
            if counts_for_achievements(participant, user)
            and self.actually_played(tournament.id, user.id)
            and self.tournament_is_eligible(tournament.id)
        ]
        items.sort(key=lambda p: p.played_at)
        self._participations[user_id] = items
        return items

    def undefeated_participations(self, user_id: int, *, until: Optional[datetime] = None) -> list[Participation]:
        """Участия, где игрок прошёл турнир X-0 (только завершённые турниры)."""
        return [
            p
            for p in self.participations(user_id, until=until)
            if self.is_complete(p.tournament_id) and self.is_undefeated(p.tournament_id, user_id)
        ]

    def decks_in_window(
        self, user_id: int, *, now: datetime, days: int = MULTICLASS_WINDOW_DAYS
    ) -> list[Participation]:
        """Участия за последние ``days`` дней, по одному на каждую РАЗНУЮ деку (самое свежее)."""
        since = now - timedelta(days=days)
        latest: dict[str, Participation] = {}
        for p in self.participations(user_id):
            if p.deck_key is None or p.played_at < since or p.played_at > now:
                continue
            known = latest.get(p.deck_key)
            if known is None or p.played_at > known.played_at:
                latest[p.deck_key] = p
        return sorted(latest.values(), key=lambda p: p.played_at)

    def club_streak(self, user_id: int, club: str, *, until: datetime) -> list[Participation]:
        """Текущая серия турниров подряд в клубе, заканчивающаяся на ``until``.

        Серия рвётся турниром клуба, который игрок пропустил (или где колоду записал не он).
        Турниры без парингов из цепочки исключаем — отменённый/пустой турнир не должен
        обнулять серию живому игроку.
        """
        club_tournaments = self._club_tournaments(club, until=until)
        mine = {p.tournament_id: p for p in self.participations(user_id, until=until)}

        streak: list[Participation] = []
        for tournament_id in reversed(club_tournaments):
            participation = mine.get(tournament_id)
            if participation is None:
                break
            streak.append(participation)
        return list(reversed(streak))

    def _club_tournaments(self, club: str, *, until: datetime) -> list[int]:
        """id турниров клуба с парингами, по возрастанию даты, не позже ``until``."""
        rows = self.db.execute(select(models.Tournament).where(models.Tournament.club == club)).scalars().all()
        dated = [(tournament_date(t), t.id) for t in rows if tournament_date(t) <= until]
        dated.sort()
        return [tid for _, tid in dated if self.tournament_is_eligible(tid)]

    def loyalist_streak(self, user_id: int, *, until: datetime) -> list[Participation]:
        """Серия подряд идущих турниров игрока на одной и той же колоде, заканчивающаяся на ``until``.

        Считаем по его собственным участиям (а не по всем турнирам клуба): пропуск турнира
        верность колоде не рвёт, а вот смена архетипа — рвёт.
        """
        mine = [p for p in self.participations(user_id, until=until) if p.deck_key]
        if not mine:
            return []
        last_deck = mine[-1].deck_key
        streak: list[Participation] = []
        for participation in reversed(mine):
            if participation.deck_key != last_deck:
                break
            streak.append(participation)
        return list(reversed(streak))

    # ------------------------------------------------------------ первый ход

    def first_recorder(self, tournament_id: int) -> Optional[int]:
        """Кто из самозаписавшихся первым записал колоду на турнир. None — таких нет.

        Момент записи — ``Participant.created_at`` (регистрация в боте идёт сразу с выбором
        колоды). При совпадении времени берём меньший id — порядок вставки.
        """
        if tournament_id in self._first_recorder:
            return self._first_recorder[tournament_id]

        rows = self.db.execute(
            select(models.Participant, models.User)
            .join(models.User, models.Participant.user_id == models.User.id)
            .where(models.Participant.tournament_id == tournament_id)
        ).all()
        eligible = [
            (participant.created_at, participant.id, participant.user_id)
            for participant, user in rows
            if counts_for_achievements(participant, user)
            and user.tg_id > 0
            and self.actually_played(tournament_id, user.id)
            and self.tournament_is_eligible(tournament_id)
        ]
        eligible.sort()
        self._first_recorder[tournament_id] = eligible[0][2] if eligible else None
        return self._first_recorder[tournament_id]

    def first_recorder_participations(self, user_id: int, *, until: Optional[datetime] = None) -> list[Participation]:
        """Участия, где игрок записал свою колоду раньше всех."""
        return [p for p in self.participations(user_id, until=until) if self.first_recorder(p.tournament_id) == user_id]

    # ------------------------------------------------------------ метаписец

    def scribe_count(self, user: models.User, *, until: Optional[datetime] = None) -> int:
        """Сколько ЧУЖИХ колод записал игрок. ``until`` — не позже даты этого турнира."""
        if until is not None:
            return len(self._scribe_rows(user, until=until))
        rows = self.db.execute(
            select(models.Participant.id, models.Tournament)
            .join(models.Tournament, models.Participant.tournament_id == models.Tournament.id)
            .where(
                models.Participant.deck_added_by_tg_id == user.tg_id,
                models.Participant.archetype_id.isnot(None),
                models.Participant.user_id != user.id,
            )
        ).all()
        return sum(1 for _, tournament in rows if self.tournament_is_eligible(tournament.id))

    def _scribe_rows(self, user: models.User, *, until: datetime) -> list[int]:
        """Чужие колоды, записанные игроком в турнирах не позже ``until``."""
        rows = self.db.execute(
            select(models.Participant.id, models.Tournament)
            .join(models.Tournament, models.Participant.tournament_id == models.Tournament.id)
            .where(
                models.Participant.deck_added_by_tg_id == user.tg_id,
                models.Participant.archetype_id.isnot(None),
                models.Participant.user_id != user.id,
            )
        ).all()
        return [
            participant_id
            for participant_id, tournament in rows
            if tournament_date(tournament) <= until and self.tournament_is_eligible(tournament.id)
        ]

    def scribe_tournament_ids(self, user: models.User, *, until: datetime) -> tuple[int, ...]:
        rows = (
            self.db.execute(
                select(models.Tournament)
                .join(models.Participant, models.Participant.tournament_id == models.Tournament.id)
                .where(
                    models.Participant.deck_added_by_tg_id == user.tg_id,
                    models.Participant.archetype_id.isnot(None),
                    models.Participant.user_id != user.id,
                )
            )
            .scalars()
            .all()
        )
        return tuple(
            tournament.id
            for tournament in sorted(rows, key=tournament_date)
            if tournament_date(tournament) <= until and self.tournament_is_eligible(tournament.id)
        )

    def scribe_names_in(self, tournament_id: int, user: models.User) -> list[str]:
        """Кого игрок записал на конкретном турнире (для причины в отчёте)."""
        rows = (
            self.db.execute(
                select(models.User)
                .join(models.Participant, models.Participant.user_id == models.User.id)
                .where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.deck_added_by_tg_id == user.tg_id,
                    models.Participant.archetype_id.isnot(None),
                    models.Participant.user_id != user.id,
                )
            )
            .scalars()
            .all()
        )
        return [display_name(u) for u in rows]


def display_name(user: models.User) -> str:
    """«Фамилия Имя» — как в остальных сообщениях бота."""
    full = " ".join(part for part in (user.last_name, user.first_name) if part).strip()
    return full or user.display_name or user.username or f"id{user.tg_id}"
