"""Debug-only simulator for the real internal Swiss engine.

The legacy :class:`services.debug_tournament.DebugTournamentService` invents its own
pairings, so it cannot exercise the real engine. This module drives
:class:`services.internal_swiss.InternalSwissService` and
:class:`services.round_results.RoundResultsService` instead: fake players are
registered through :class:`services.tournament.TournamentService`, results are
written with ``RoundResultsService.admin_set`` and rounds are created with
``InternalSwissService.generate_next_round``. Nothing here reimplements a rule.

Safety (a debug simulator must never reach a real human):

* the tournament must belong to a chat from ``settings.chat_ids`` and the process
  must run with ``settings.DEBUG``;
* fake users get negative ``tg_id``, so every DM path that filters ``tg_id > 0``
  (round notifications, Swiss requirement reminders, achievements) skips them;
* fake participants are ``added_by_admin=True``, which blocks round notifications
  even if a fake id ever became positive;
* the CLI never calls ``bot.send_message``: it only writes to the database.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.config import app_cfg, settings
from core.schemas import TournamentCreate
from services.archetype import ArchetypeService
from services.decklists import MAX_DECKLIST_LENGTH
from services.endstep_table_titles import ENDSTEP_RU_CLUB
from services.internal_swiss import InternalSwissService, SwissStanding, playoff_rounds
from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService
from services.tournament import MAX_ACTIVE_TOURNAMENTS_PER_CLUB, TournamentService
from services.user import UserService
from utils.seed import PAUPER_ARCHETYPES

DEFAULT_PLAYERS = 110
DEFAULT_SWISS_ROUNDS = 7
DEFAULT_PLAYOFF_SIZE = 8
MIN_PLAYERS = 2
MAX_PLAYERS = 512
MIN_SWISS_ROUNDS = 3
MAX_SWISS_ROUNDS = 20
MIN_PLAYOFF_SIZE = 8
MAX_PLAYOFF_SIZE = 16
_DEBUG_TG_ID_FLOOR = -9_000_000
_DEBUG_USERNAME_PREFIX = "dbg_sw"
_DEBUG_USERNAME_GLOB = "dbg_sw%"

# Swiss score is drawn from a weighted bag so a 110-player field produces a
# realistic spread instead of a perfectly uniform 33% win rate.
_SWISS_SCORES = (
    (2, 0, 34),
    (2, 1, 24),
    (1, 0, 8),
    (1, 1, 5),
    (0, 0, 2),
    (0, 1, 3),
    (0, 2, 12),
    (1, 2, 12),
)
_PLAYOFF_SCORES = ((2, 0, 55), (2, 1, 25), (1, 2, 15), (0, 2, 5))
_SWISS_SCORE_WEIGHTS = tuple(weight for _, _, weight in _SWISS_SCORES)
_PLAYOFF_SCORE_WEIGHTS = tuple(weight for _, _, weight in _PLAYOFF_SCORES)

_DECKLIST_BODY = """4 Mountain
4 Island
4 Swiftwater Cliffs
4 Blood Moon
4 Lightning Bolt
4 Lightning Strike
4 Gut Shot
4 Gitaxian Probe
4 Browbeat
4 Pyrokinesis
4 Spellstutter Sprite
4 Kor Skyfisher
2 Merchant of the Vale
2 Firebolt
2 Flame Rift
SB: 4 Chain Lightning
"""


@dataclass(frozen=True)
class DebugSwissFillResult:
    added: int
    total: int


@dataclass(frozen=True)
class DebugSwissStepResult:
    round_number: int
    planned_rounds: int
    matches: int
    completed_previous: int


@dataclass(frozen=True)
class DebugSwissRunResult:
    rounds: list[DebugSwissStepResult]
    played: int
    planned: int
    last_round_scored: int = 0

    @property
    def completed(self) -> bool:
        return self.planned > 0 and self.played >= self.planned


@dataclass(frozen=True)
class DebugSwissStatus:
    tournament_id: int
    title: str
    status: str
    round_number: int
    planned_rounds: int
    active_players: int
    swiss_rounds: int
    playoff_size: int
    large_format: bool
    scores_collected: bool
    can_autoplay: bool


class DebugSwissService:
    """Create and drive a fake internal-Swiss field through the real engine."""

    def __init__(self, db: Session, *, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random()
        self.tournaments = TournamentService(db)
        self.users = UserService(db)
        self.results = RoundResultsService(db)
        self.archetypes = ArchetypeService(db)
        self.engine = InternalSwissService(db, rng=random.Random(self.rng.random()))

    # ------------------------------------------------------------ field setup

    def create_tournament(
        self,
        *,
        players: int = DEFAULT_PLAYERS,
        rounds: int = DEFAULT_SWISS_ROUNDS,
        playoff_size: int = DEFAULT_PLAYOFF_SIZE,
        admin_tg_id: int | None = None,
        title: str | None = None,
    ) -> models.Tournament:
        """Create a debug internal-Swiss tournament ready for round 1."""
        self._ensure_debug_config()
        players = self._validate_players(players)
        rounds = self._validate_rounds(rounds)
        playoff_size = self._validate_playoff(playoff_size)
        chat_id = self._default_chat_id()
        self._ensure_active_slot()
        created = self.tournaments.create_tournament(
            TournamentCreate(
                title=title or f"🐞 DEBUG Swiss · {players} игроков",
                chat_id=chat_id,
                club=ENDSTEP_RU_CLUB,
                is_online=True,
                is_draft=False,
                engine_mode=models.TournamentEngineMode.INTERNAL_SWISS,
                registration_close_at=models.utc_now(),
                created_by_tg_id=admin_tg_id,
                decklist_reminders_enabled=True,
            )
        )
        tournament = self._tournament(created.id)
        tournament.swiss_large_format = True
        tournament.swiss_rounds = rounds
        tournament.playoff_size = playoff_size
        tournament.show_round_pairings = True
        self.db.commit()
        return self._tournament(tournament.id)

    def close_active_debug_tournaments(self) -> list[models.Tournament]:
        """Close every still-open Endstep tournament so a fresh setup fits the club slot limit."""
        self._ensure_debug_config()
        rows = self.active_club_tournaments()
        for tournament in rows:
            self.tournaments.close_tournament(tournament.id)
        return rows

    # ------------------------------------------------------------ forced close

    def active_club_tournaments(self) -> list[models.Tournament]:
        """Still-open tournaments of the Endstep club — the ones the slot limit counts."""
        self._ensure_debug_config()
        return list(
            self.db.execute(
                select(models.Tournament)
                .where(
                    models.Tournament.club == ENDSTEP_RU_CLUB,
                    models.Tournament.status != models.TournamentStatus.CLOSED,
                )
                .order_by(models.Tournament.id)
            ).scalars()
        )

    def force_close(self, tournament_id: int, admin_tg_id: int) -> models.Tournament:
        """Close a debug Swiss even if its planned rounds were never played.

        The normal admin close goes through :meth:`InternalSwissService.finish`, which
        refuses an unfinished Swiss — correct for real tournaments, useless when you just
        want to reset a debug one. Places are left empty on purpose: the field is thrown
        away, and inventing final places for an unfinished Swiss would pollute rankings.
        """
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        self._ensure_actor(admin_tg_id, tournament)
        if tournament.status == models.TournamentStatus.CLOSED:
            raise RoundResultError("Турнир уже закрыт.")
        self.tournaments.close_tournament(tournament_id, admin_tg_id)
        return self._tournament(tournament_id)

    def force_close_active(self, admin_tg_id: int) -> list[models.Tournament]:
        """Free every club slot: close all still-open Endstep tournaments, unfinished or not."""
        self._ensure_debug_config()
        if not self.users.is_privileged(admin_tg_id):
            raise RoundResultError("У актора нет прав администратора.")
        rows = self.active_club_tournaments()
        for tournament in rows:
            self.tournaments.close_tournament(tournament.id, admin_tg_id)
        return rows

    def fill_players(self, tournament_id: int, count: int = DEFAULT_PLAYERS) -> DebugSwissFillResult:
        """Register fake players with an archetype and a decklist each."""
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        if tournament.status != models.TournamentStatus.REGISTRATION:
            raise RoundResultError("Фейковых игроков можно добавить только до первого раунда.")
        count = self._validate_players(count)
        active = self._participants(tournament_id)
        to_add = max(0, count - len(active))
        archetypes = self._archetype_pool()
        if not archetypes:
            raise RoundResultError("В базе нет ни одного архетипа — нечего назначать фейкам.")
        next_tg_id = self.db.execute(select(func.min(models.User.tg_id)).where(models.User.tg_id < 0)).scalar()
        next_tg_id = min(next_tg_id or _DEBUG_TG_ID_FLOOR, _DEBUG_TG_ID_FLOOR) - 1
        number = self._next_debug_number()

        for _ in range(to_add):
            user = models.User(
                tg_id=next_tg_id,
                username=f"{_DEBUG_USERNAME_PREFIX}{tournament_id}_p{number:03d}",
                first_name="Тест",
                last_name=f"Игрок{number:03d}",
            )
            self.db.add(user)
            self.db.flush()
            archetype = archetypes[number % len(archetypes)]
            self.tournaments.register_participant(
                tournament_id=tournament_id,
                user_id=user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
                deck_deferred=False,
            )
            participant = self.db.execute(
                select(models.Participant).where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.user_id == user.id,
                )
            ).scalar_one()
            participant.decklist = models.ParticipantDecklist(
                raw_text=self._decklist_text(archetype.name, number),
                created_at=models.utc_now(),
                updated_at=models.utc_now(),
            )
            next_tg_id -= 1
            number += 1

        self.db.commit()
        return DebugSwissFillResult(added=to_add, total=len(self._participants(tournament_id)))

    # ------------------------------------------------------------- autoplay

    def autoplay_round(self, tournament_id: int, admin_tg_id: int) -> DebugSwissStepResult:
        """Score the current round randomly, then create the next real one.

        When every planned round is already generated this only scores the last
        round (matches=0), so a partially played Swiss always becomes finishable.
        """
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        self._ensure_actor(admin_tg_id, tournament)
        current = self.results.latest_round_number(tournament_id)
        completed = self._complete_round_randomly(tournament, current, admin_tg_id) if current else 0
        planned = self.engine.total_planned_rounds(self._tournament(tournament_id))
        if current is not None and current >= planned:
            return DebugSwissStepResult(
                round_number=current,
                planned_rounds=planned,
                matches=0,
                completed_previous=completed,
            )
        generated = self.engine.generate_next_round(tournament_id, admin_tg_id)
        return DebugSwissStepResult(
            round_number=generated.round_number,
            planned_rounds=generated.planned_rounds,
            matches=generated.matches,
            completed_previous=completed,
        )

    def autoplay_all(self, tournament_id: int, admin_tg_id: int) -> DebugSwissRunResult:
        """Play and score every planned round; the tournament stays ONGOING for a manual finish."""
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        self._ensure_actor(admin_tg_id, tournament)
        planned = self.engine.total_planned_rounds(tournament)
        guard = planned + 2
        steps: list[DebugSwissStepResult] = []
        for _ in range(guard):
            current = self.results.latest_round_number(tournament_id)
            if current is not None and current >= planned:
                break
            steps.append(self.autoplay_round(tournament_id, admin_tg_id))
        final = self._tournament(tournament_id)
        played = self.results.latest_round_number(tournament_id) or 0
        last_scored = 0
        if played >= planned:
            # Score the final round too, otherwise finish() rejects an unscored round.
            last_scored = self._complete_round_randomly(final, played, admin_tg_id)
        return DebugSwissRunResult(rounds=steps, played=played, planned=planned, last_round_scored=last_scored)

    def finish(self, tournament_id: int, admin_tg_id: int) -> list[SwissStanding]:
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        self._ensure_actor(admin_tg_id, tournament)
        return self.engine.finish(tournament_id, admin_tg_id)

    def standings(self, tournament_id: int) -> list[SwissStanding]:
        self._ensure_debug_target(self._tournament(tournament_id))
        return self.engine.standings(tournament_id)

    def status(self, tournament_id: int) -> DebugSwissStatus:
        tournament = self._tournament(tournament_id)
        self._ensure_debug_target(tournament)
        settings_view = self.engine.get_swiss_settings(tournament_id)
        round_number = self.results.latest_round_number(tournament_id) or 0
        planned = self.engine.total_planned_rounds(tournament)
        # autoplay_round() scores the current round itself, so any generated round can advance.
        scores_collected = round_number == 0 or self.results.is_round_ready(tournament_id, round_number)
        can_autoplay = tournament.status != models.TournamentStatus.CLOSED and (
            round_number < planned or not scores_collected
        )
        return DebugSwissStatus(
            tournament_id=tournament.id,
            title=tournament.title,
            status=tournament.status.value,
            round_number=round_number,
            planned_rounds=planned,
            active_players=settings_view.active_players,
            swiss_rounds=tournament.swiss_rounds or 0,
            playoff_size=settings_view.playoff_size or 0,
            large_format=bool(tournament.swiss_large_format),
            scores_collected=scores_collected,
            can_autoplay=can_autoplay,
        )

    # -------------------------------------------------------------- internals

    def _complete_round_randomly(self, tournament: models.Tournament, round_number: int, admin_tg_id: int) -> int:
        completed = 0
        playoff = round_number > (tournament.swiss_rounds or 0)
        for match in self.results.list_round(tournament.id, round_number):
            if match.player2_name is None or match.status in FINAL_STATUSES:
                continue
            left, right = self._score(playoff)
            self.results.admin_set(match.id, admin_tg_id, left, right)
            completed += 1
        return completed

    def _score(self, playoff: bool) -> tuple[int, int]:
        bag = _PLAYOFF_SCORES if playoff else _SWISS_SCORES
        weights = _PLAYOFF_SCORE_WEIGHTS if playoff else _SWISS_SCORE_WEIGHTS
        left, right, _ = self.rng.choices(bag, weights=weights, k=1)[0]
        return left, right

    def _archetype_pool(self) -> list[models.Archetype]:
        rows = list(
            self.db.execute(
                select(models.Archetype)
                .where(models.Archetype.is_custom.is_(False))
                .order_by(models.Archetype.meta_rank.asc().nullslast(), models.Archetype.name)
            ).scalars()
        )
        if rows:
            return rows
        for data in PAUPER_ARCHETYPES:
            self.archetypes.get_or_create_by_name(data["name"])
        return list(
            self.db.execute(select(models.Archetype).order_by(models.Archetype.meta_rank.asc().nullslast())).scalars()
        )

    def _ensure_active_slot(self) -> None:
        """A club keeps at most two open tournaments; the CLI reports this before crashing."""
        active = self.db.execute(
            select(func.count(models.Tournament.id)).where(
                models.Tournament.club == ENDSTEP_RU_CLUB,
                models.Tournament.status != models.TournamentStatus.CLOSED,
            )
        ).scalar_one()
        if active >= MAX_ACTIVE_TOURNAMENTS_PER_CLUB:
            raise RoundResultError(
                f"У клуба уже {active} активных турниров (лимит {MAX_ACTIVE_TOURNAMENTS_PER_CLUB}). "
                "Сначала выполни `swiss close-active`."
            )

    def _next_debug_number(self) -> int:
        used = set()
        for (username,) in self.db.execute(
            select(models.User.username).where(models.User.username.like(_DEBUG_USERNAME_GLOB))
        ):
            suffix = (username or "").rsplit("_p", 1)[-1]
            if suffix.isdigit():
                used.add(int(suffix))
        number = 1
        while number in used:
            number += 1
        return number

    @staticmethod
    def _decklist_text(archetype_name: str, number: int) -> str:
        header = f"// Debug decklist #{number} — {archetype_name}\n"
        return (header + _DECKLIST_BODY)[:MAX_DECKLIST_LENGTH]

    def _participants(self, tournament_id: int) -> list[models.Participant]:
        return list(
            self.db.execute(
                select(models.Participant)
                .where(
                    models.Participant.tournament_id == tournament_id,
                    models.Participant.dropped_at.is_(None),
                )
                .order_by(models.Participant.id)
            ).scalars()
        )

    def _tournament(self, tournament_id: int) -> models.Tournament:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise RoundResultError("Турнир не найден.")
        return tournament

    def _ensure_actor(self, admin_tg_id: int, tournament: models.Tournament) -> None:
        if self.users.can_manage_tournament(admin_tg_id, tournament) or self.users.is_privileged_for_tournament(
            admin_tg_id, tournament
        ):
            return
        raise RoundResultError(
            "У актора нет прав организатора этого турнира. Передай --admin-id администратора debug-базы."
        )

    @staticmethod
    def _ensure_debug_config() -> None:
        if not settings.DEBUG:
            raise RoundResultError("Симулятор Swiss доступен только при BOT_ENV=debug.")

    @classmethod
    def _ensure_debug_target(cls, tournament: models.Tournament) -> None:
        cls._ensure_debug_config()
        if tournament.chat_id not in settings.chat_ids:
            raise RoundResultError("Симулятор Swiss работает только с турнирами debug-чатов.")

    @staticmethod
    def _default_chat_id() -> int:
        chat_id = app_cfg.endstep_ru_chat_id
        if not chat_id:
            raise RoundResultError("В debug-конфиге не задан endstep_ru_chat_id.")
        return chat_id

    @staticmethod
    def _validate_players(count: int) -> int:
        if not MIN_PLAYERS <= count <= MAX_PLAYERS:
            raise RoundResultError(f"Число игроков должно быть от {MIN_PLAYERS} до {MAX_PLAYERS}.")
        return count

    @staticmethod
    def _validate_rounds(rounds: int) -> int:
        if not MIN_SWISS_ROUNDS <= rounds <= MAX_SWISS_ROUNDS:
            raise RoundResultError(f"Число Swiss-раундов должно быть от {MIN_SWISS_ROUNDS} до {MAX_SWISS_ROUNDS}.")
        return rounds

    @staticmethod
    def _validate_playoff(playoff_size: int) -> int:
        if playoff_size not in (MIN_PLAYOFF_SIZE, MAX_PLAYOFF_SIZE):
            raise RoundResultError("Плей-офф поддерживается только на 8 или 16 мест.")
        return playoff_size

    @staticmethod
    def planned_rounds_for(swiss_rounds: int, playoff_size: int) -> int:
        return swiss_rounds + playoff_rounds(playoff_size)
