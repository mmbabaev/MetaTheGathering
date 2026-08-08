"""Правила ачивок: из контекста турнира → выдачи и обновления прогресса.

Каждое правило считает своё значение счётчика ПОЛНОСТЬЮ из первичных данных (а не
прибавляет единицу к сохранённому), поэтому повторный прогон турнира даёт тот же
результат — это и есть идемпотентность движка.

Вместе со значением правило возвращает ``evidence`` — человекочитаемую причину из
истории («4-0 на Elves», «Mono Red (17.07) · Elves (24.07)»), которая идёт в отчёт.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional, Protocol

from sqlalchemy import select

from core import models
from services.achievements import definitions
from services.achievements.context import TournamentContext
from services.achievements.history import Participation
from services.achievements.registry import validate_registry

EVIDENCE_MAX = 500  # колонка 512, оставляем запас на многоточие
_EVIDENCE_ITEMS = 4  # сколько фактов перечисляем, дальше «…»


@dataclass(frozen=True)
class Award:
    """Ачивка, заслуженная игроком (может быть уже выданной — фильтрует сервис)."""

    user_id: int
    code: str
    level: int
    progress_value: Optional[int]
    evidence: str


@dataclass(frozen=True)
class ProgressUpdate:
    """Значение счётчика на пути к следующему уровню."""

    user_id: int
    code: str
    value: int
    threshold: int
    next_level: int
    evidence: str


@dataclass(frozen=True)
class RuleError:
    """Безопасное описание сбоя правила без потенциально приватного exception message."""

    code: str
    error_type: str


@dataclass
class RuleOutcome:
    awards: list[Award] = field(default_factory=list)
    progress: list[ProgressUpdate] = field(default_factory=list)
    rule_errors: list[RuleError] = field(default_factory=list)
    rules_evaluated: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def extend(self, other: "RuleOutcome") -> None:
        self.awards.extend(other.awards)
        self.progress.extend(other.progress)

    @property
    def status(self) -> str:
        if not self.rule_errors:
            return "completed"
        if self.rules_evaluated and len(self.rule_errors) >= self.rules_evaluated:
            return "failed"
        return "partial"


class AchievementRule(Protocol):
    code: str

    def evaluate(self, ctx: TournamentContext) -> RuleOutcome: ...


def _short_date(participation: Participation) -> str:
    return participation.played_at.strftime("%d.%m")


def _deck_list(items: list[Participation]) -> str:
    """«Mono Red (17.07) · Elves (24.07)», не длиннее EVIDENCE_MAX."""
    parts = [f"{p.archetype_name or '—'} ({_short_date(p)})" for p in items[-_EVIDENCE_ITEMS:]]
    if len(items) > _EVIDENCE_ITEMS:
        parts.insert(0, "…")
    return _clip(" · ".join(parts))


def _date_list(items: list[Participation]) -> str:
    """«03.07 · 10.07 · 17.07 · 24.07»."""
    parts = [_short_date(p) for p in items[-_EVIDENCE_ITEMS:]]
    if len(items) > _EVIDENCE_ITEMS:
        parts.insert(0, "…")
    return _clip(" · ".join(parts))


def _clip(text: str) -> str:
    return text if len(text) <= EVIDENCE_MAX else text[: EVIDENCE_MAX - 1] + "…"


class CounterRule:
    """Базовое правило со счётчиком: значение → взятые уровни + прогресс до следующего."""

    code: str = ""

    def audience(self, ctx: TournamentContext) -> Iterable[int]:
        """Кого пересчитываем. По умолчанию — прошедшие гейт зачёта участники турнира."""
        return sorted(ctx.eligible_user_ids)

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        """(значение счётчика, причина). Переопределяется в наследниках."""
        raise NotImplementedError

    def evaluate(self, ctx: TournamentContext) -> RuleOutcome:
        outcome = RuleOutcome()
        for user_id in self.audience(ctx):
            value, evidence = self.value_for(ctx, user_id)
            if value <= 0:
                continue
            for definition in definitions.reached_levels(self.code, value):
                outcome.awards.append(
                    Award(
                        user_id=user_id,
                        code=self.code,
                        level=definition.level,
                        progress_value=value,
                        evidence=evidence,
                    )
                )
            nxt = definitions.next_level_for(self.code, value)
            if nxt is not None and nxt.threshold is not None:
                outcome.progress.append(
                    ProgressUpdate(
                        user_id=user_id,
                        code=self.code,
                        value=value,
                        threshold=nxt.threshold,
                        next_level=nxt.level,
                        evidence=evidence,
                    )
                )
        return outcome


class DebutRule:
    """🎖 Дебют — впервые сам записал свою колоду. Одноразовая, без прогресса."""

    code = definitions.Codes.DEBUT

    def evaluate(self, ctx: TournamentContext) -> RuleOutcome:
        outcome = RuleOutcome()
        for user_id in sorted(ctx.eligible_user_ids):
            participations = ctx.history.participations(user_id, until=ctx.played_at)
            if not participations or participations[0].tournament_id != ctx.tournament.id:
                continue
            deck = ctx.deck_name(user_id) or "—"
            outcome.awards.append(
                Award(
                    user_id=user_id,
                    code=self.code,
                    level=1,
                    progress_value=None,
                    evidence=_clip(f"первая своя колода: {deck}"),
                )
            )
        return outcome


class FirstDeckRule(CounterRule):
    """⚡ Первый ход — записал колоду раньше всех на турнире."""

    code = definitions.Codes.FIRST_DECK

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        items = ctx.history.first_recorder_participations(user_id, until=ctx.played_at)
        if not items:
            return 0, ""
        was_first_here = any(p.tournament_id == ctx.tournament.id for p in items)
        prefix = "первым записал колоду сегодня" if was_first_here else "раньше всех записывал"
        return len(items), _clip(f"{prefix}: {_date_list(items)}")


class UndefeatedRule(CounterRule):
    """🏆 Без поражений — турниры, пройденные X-0."""

    code = definitions.Codes.UNDEFEATED

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        items = ctx.history.undefeated_participations(user_id, until=ctx.played_at)
        if not items:
            return 0, ""
        if user_id in ctx.undefeated_user_ids:
            record = ctx.records.get(user_id)
            deck = ctx.deck_name(user_id) or "—"
            head = f"{record.record if record else 'X-0'} на {deck}"
        else:
            head = "без поражений ранее"
        return len(items), _clip(f"{head}; всего X-0: {len(items)} ({_date_list(items)})")


class ScribeRule(CounterRule):
    """🧙 Метаписец — записал чужие колоды.

    Аудитория шире остальных правил: сюда попадают все, кто записывал колоды на этом
    турнире, даже если сам в нём не играл.
    """

    code = definitions.Codes.SCRIBE

    def audience(self, ctx: TournamentContext) -> Iterable[int]:
        tg_ids = (
            ctx.history.db.execute(
                select(models.Participant.deck_added_by_tg_id).where(
                    models.Participant.tournament_id == ctx.tournament.id,
                    models.Participant.deck_added_by_tg_id.isnot(None),
                    models.Participant.archetype_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        users = ctx.history.db.execute(select(models.User).where(models.User.tg_id.in_(set(tg_ids)))).scalars().all()
        return sorted(u.id for u in users if u.tg_id > 0)

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        user = ctx.users.get(user_id) or ctx.history.db.get(models.User, user_id)
        if user is None:
            return 0, ""
        total = ctx.history.scribe_count(user, until=ctx.played_at)
        if total <= 0:
            return 0, ""
        today = ctx.history.scribe_names_in(ctx.tournament.id, user)
        if today:
            shown = ", ".join(today[:_EVIDENCE_ITEMS]) + ("…" if len(today) > _EVIDENCE_ITEMS else "")
            return total, _clip(f"записал сегодня: {shown}")
        return total, _clip(f"всего чужих колод: {total}")


class RegularRule(CounterRule):
    """📅 Завсегдатай — турниры подряд в одном клубе."""

    code = definitions.Codes.REGULAR

    def audience(self, ctx: TournamentContext) -> Iterable[int]:
        if not ctx.tournament.club:
            return []  # турнир вне клуба серию не двигает
        return sorted(ctx.eligible_user_ids)

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        club = ctx.tournament.club
        if not club:
            return 0, ""
        streak = ctx.history.club_streak(user_id, club, until=ctx.played_at)
        if not streak:
            return 0, ""
        return len(streak), _clip(f"{club}: {_date_list(streak)}")


class MulticlassRule(CounterRule):
    """🎭 Мультикласс — разные колоды за 90 дней."""

    code = definitions.Codes.MULTICLASS

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        decks = ctx.history.decks_in_window(user_id, now=ctx.played_at)
        if not decks:
            return 0, ""
        return len(decks), _clip(f"за 90 дней: {_deck_list(decks)}")


class LoyalistRule(CounterRule):
    """💍 Однолюб — турниры подряд на одной и той же колоде."""

    code = definitions.Codes.LOYALIST

    def value_for(self, ctx: TournamentContext, user_id: int) -> tuple[int, str]:
        streak = ctx.history.loyalist_streak(user_id, until=ctx.played_at)
        if not streak:
            return 0, ""
        deck = streak[-1].archetype_name or "—"
        return len(streak), _clip(f"{deck}: {_date_list(streak)}")


def default_rules() -> list[AchievementRule]:
    """Все правила в порядке показа."""
    rules: list[AchievementRule] = [
        DebutRule(),
        FirstDeckRule(),
        UndefeatedRule(),
        ScribeRule(),
        RegularRule(),
        MulticlassRule(),
        LoyalistRule(),
    ]
    # Выполняется до чтения/записи турнирных данных.
    validate_registry(definitions.all_definitions(), definitions.CODE_ORDER, rules)
    return rules
