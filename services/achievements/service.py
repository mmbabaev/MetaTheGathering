"""Сервис ачивок: оценка турнира, идемпотентная выдача, чтение полки игрока.

Точка входа для всех колл-сайтов — ``process_tournament``: она безопасна при любом
числе повторных вызовов (импорт AetherHub за вечер повторяется десятки раз).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.achievements import definitions
from services.achievements.context import SkippedPlayer, TournamentContext, build_context
from services.achievements.definitions import AchievementDef
from services.achievements.history import AchievementHistory, display_name, tournament_date
from services.achievements.rules import AchievementRule, Award, ProgressUpdate, RuleError, RuleOutcome, default_rules

logger = logging.getLogger(__name__)

ENGINE_VERSION = 1


@dataclass(frozen=True)
class GrantedAchievement:
    """Только что выданная ачивка — для отчёта."""

    user_id: int
    player: str
    definition: AchievementDef
    evidence: str
    progress_value: Optional[int]


@dataclass(frozen=True)
class ProgressChange:
    """Сдвиг счётчика за этот турнир — для отчёта."""

    user_id: int
    player: str
    definition: AchievementDef  # следующий уровень, к которому идём
    value: int
    previous: int
    threshold: int
    evidence: str

    @property
    def delta(self) -> int:
        return self.value - self.previous


@dataclass
class AppliedResult:
    """Что реально изменилось на этом турнире."""

    tournament_id: int
    title: str
    club: Optional[str]
    granted: list[GrantedAchievement] = field(default_factory=list)
    progress_changes: list[ProgressChange] = field(default_factory=list)
    skipped: list[SkippedPlayer] = field(default_factory=list)
    status: str = "completed"
    rule_errors: list[RuleError] = field(default_factory=list)
    processing_run_id: Optional[int] = None

    @property
    def is_empty(self) -> bool:
        return not self.granted and not self.progress_changes and not self.rule_errors


@dataclass
class BackfillReport:
    """Итог прогона по истории: что выдалось бы (dry-run) или выдалось (apply)."""

    dry_run: bool
    tournaments: int = 0  # сколько турниров реально обсчитано
    skipped: int = 0  # пропущено (нет парингов / не у всех матчей счёт)
    granted: list[GrantedAchievement] = field(default_factory=list)

    @property
    def by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.granted:
            counts[item.definition.code] = counts.get(item.definition.code, 0) + 1
        return counts

    @property
    def by_player(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.granted:
            counts[item.player] = counts.get(item.player, 0) + 1
        return counts


@dataclass(frozen=True)
class AchievementView:
    """Строка полки игрока: определение + статус + прогресс."""

    definition: AchievementDef
    unlocked: bool
    awarded_at: Optional[datetime] = None
    evidence: Optional[str] = None
    progress: Optional[int] = None  # текущее значение счётчика, если ачивка ещё не открыта


class AchievementService:
    def __init__(
        self,
        db: Session,
        rules: Optional[list[AchievementRule]] = None,
        history: Optional[AchievementHistory] = None,
    ) -> None:
        self.db = db
        self.rules = rules if rules is not None else default_rules()
        self._history = history

    # ------------------------------------------------------------- оценка

    def build_context(self, tournament_id: int) -> Optional[TournamentContext]:
        history = self._history if self._history is not None else AchievementHistory(self.db)
        return build_context(self.db, tournament_id, history)

    def evaluate_for_tournament(self, tournament_id: int) -> tuple[Optional[TournamentContext], RuleOutcome]:
        """Прогнать правила по турниру. В БД ничего не пишет.

        Возвращает (контекст, результат). Контекст нужен вызывающему для имён и списка
        «не в зачёт». None — турнира нет или он ещё не завершён.
        """
        ctx = self.build_context(tournament_id)
        if ctx is None:
            return None, RuleOutcome()
        if not ctx.history.is_complete(tournament_id):
            logger.info("[achievements] tournament #%s is not complete yet — skip", tournament_id)
            return None, RuleOutcome()

        outcome = RuleOutcome(started_at=models.utc_now(), rules_evaluated=len(self.rules))
        for rule in self.rules:
            try:
                outcome.extend(rule.evaluate(ctx))
            except Exception as exc:  # noqa: BLE001 — сбой одного правила не должен ронять остальные
                outcome.rule_errors.append(RuleError(code=rule.code, error_type=type(exc).__name__))
                logger.exception("[achievements] rule %s failed on tournament #%s", rule.code, tournament_id)
        outcome.completed_at = models.utc_now()
        return ctx, outcome

    # ------------------------------------------------------------- запись

    def process_tournament(
        self, tournament_id: int, *, notified: bool = False, commit: bool = True
    ) -> Optional[AppliedResult]:
        """Оценить турнир и записать изменения. None — считать нечего (турнир не готов).

        Повторный вызов вернёт результат с пустыми ``granted``/``progress_changes``.
        """
        ctx, outcome = self.evaluate_for_tournament(tournament_id)
        if ctx is None:
            return None
        return self.apply(ctx, outcome, notified=notified, commit=commit)

    def apply(
        self, ctx: TournamentContext, outcome: RuleOutcome, *, notified: bool = False, commit: bool = True
    ) -> AppliedResult:
        result = AppliedResult(
            tournament_id=ctx.tournament.id,
            title=ctx.tournament.title,
            club=ctx.tournament.club,
            skipped=list(ctx.skipped),
            status=outcome.status,
            rule_errors=list(outcome.rule_errors),
        )
        for award in outcome.awards:
            granted = self._grant(ctx, award, notified=notified)
            if granted is not None:
                result.granted.append(granted)
        for update in outcome.progress:
            change = self._update_progress(ctx, update)
            if change is not None:
                result.progress_changes.append(change)
        run = models.AchievementProcessingRun(
            tournament_id=ctx.tournament.id,
            status=result.status,
            engine_version=ENGINE_VERSION,
            rules_total=outcome.rules_evaluated,
            rules_failed=len(outcome.rule_errors),
            granted_count=len(result.granted),
            progress_changes_count=len(result.progress_changes),
            skipped_count=len(result.skipped),
            rule_errors_json=(
                json.dumps(
                    [{"code": error.code, "error_type": error.error_type} for error in outcome.rule_errors],
                    ensure_ascii=False,
                )
                if outcome.rule_errors
                else None
            ),
            started_at=outcome.started_at or models.utc_now(),
            completed_at=outcome.completed_at or models.utc_now(),
        )
        self.db.add(run)
        self.db.flush()
        result.processing_run_id = run.id
        if commit:
            self.db.commit()

        result.granted.sort(key=lambda g: (definitions.CODE_ORDER.index(g.definition.code), g.player))
        result.progress_changes.sort(key=lambda p: (definitions.CODE_ORDER.index(p.definition.code), p.player))
        return result

    def _grant(self, ctx: TournamentContext, award: Award, *, notified: bool) -> Optional[GrantedAchievement]:
        definition = definitions.get(award.code, award.level)
        if definition is None:
            return None
        existing = self.db.execute(
            select(models.UserAchievement).where(
                models.UserAchievement.user_id == award.user_id,
                models.UserAchievement.code == award.code,
                models.UserAchievement.level == award.level,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None  # уже выдана — идемпотентность

        now = models.utc_now()
        self.db.add(
            models.UserAchievement(
                user_id=award.user_id,
                code=award.code,
                level=award.level,
                tournament_id=ctx.tournament.id,
                progress_value=award.progress_value,
                evidence=award.evidence or None,
                awarded_at=now,
                notified_at=now if notified else None,
            )
        )
        return GrantedAchievement(
            user_id=award.user_id,
            player=self._player_name(ctx, award.user_id),
            definition=definition,
            evidence=award.evidence,
            progress_value=award.progress_value,
        )

    def _update_progress(self, ctx: TournamentContext, update: ProgressUpdate) -> Optional[ProgressChange]:
        definition = definitions.get(update.code, update.next_level)
        if definition is None:
            return None
        row = self.db.execute(
            select(models.UserAchievementProgress).where(
                models.UserAchievementProgress.user_id == update.user_id,
                models.UserAchievementProgress.code == update.code,
            )
        ).scalar_one_or_none()
        previous = row.value if row is not None else 0
        if row is None:
            row = models.UserAchievementProgress(user_id=update.user_id, code=update.code, value=update.value)
            self.db.add(row)
        row.value = update.value
        row.tournament_id = ctx.tournament.id
        row.evidence = update.evidence or None

        if update.value == previous:
            return None  # ничего не сдвинулось — в отчёт не попадает
        return ProgressChange(
            user_id=update.user_id,
            player=self._player_name(ctx, update.user_id),
            definition=definition,
            value=update.value,
            previous=previous,
            threshold=update.threshold,
            evidence=update.evidence,
        )

    def _player_name(self, ctx: TournamentContext, user_id: int) -> str:
        if user_id in ctx.users:
            return display_name(ctx.users[user_id])
        user = self.db.get(models.User, user_id)
        return display_name(user) if user is not None else f"user#{user_id}"

    # ------------------------------------------------------------ бэкафилл

    def backfill(self, *, club: Optional[str] = None, dry_run: bool = True) -> BackfillReport:
        """Прогнать движок по всей истории турниров, от старых к новым.

        Идёт в хронологическом порядке, потому что правила смотрят историю «на дату турнира»:
        так ачивка привязывается к тому турниру, где она реально взята, а не к первому
        попавшемуся. Выдачи помечаются ``notified_at`` — за прошлые турниры игрокам (и
        владельцу) писать нечего, иначе первое же включение уведомлений разошлёт пачку старых.

        ``dry_run=True`` (по умолчанию) ничего не пишет — только собирает отчёт.
        """
        report = BackfillReport(dry_run=dry_run)
        seen: set[tuple[int, str, int]] = set()  # (user_id, code, level) — чтобы dry-run не дублировал

        for tournament_id in self._tournaments_in_order(club):
            ctx, outcome = self.evaluate_for_tournament(tournament_id)
            if ctx is None:
                report.skipped += 1
                continue
            report.tournaments += 1

            if dry_run:
                for award in outcome.awards:
                    key = (award.user_id, award.code, award.level)
                    if key in seen or self._already_granted(award):
                        continue
                    seen.add(key)
                    definition = definitions.get(award.code, award.level)
                    if definition is None:
                        continue
                    report.granted.append(
                        GrantedAchievement(
                            user_id=award.user_id,
                            player=self._player_name(ctx, award.user_id),
                            definition=definition,
                            evidence=award.evidence,
                            progress_value=award.progress_value,
                        )
                    )
                continue

            applied = self.apply(ctx, outcome, notified=True)
            report.granted.extend(applied.granted)

        return report

    def _tournaments_in_order(self, club: Optional[str]) -> list[int]:
        """id турниров по возрастанию даты (started_at, иначе created_at)."""
        stmt = select(models.Tournament)
        if club:
            stmt = stmt.where(models.Tournament.club == club)
        tournaments = self.db.execute(stmt).scalars().all()
        dated = [(tournament_date(t), t.id) for t in tournaments]
        dated.sort()
        return [tournament_id for _, tournament_id in dated]

    def _already_granted(self, award: Award) -> bool:
        return (
            self.db.execute(
                select(models.UserAchievement.id).where(
                    models.UserAchievement.user_id == award.user_id,
                    models.UserAchievement.code == award.code,
                    models.UserAchievement.level == award.level,
                )
            ).scalar_one_or_none()
            is not None
        )

    # ------------------------------------------------------------- чтение

    def list_for_user(self, user_id: int) -> list[AchievementView]:
        """Полка игрока: все определения в порядке показа + статус и прогресс."""
        unlocked = {
            (row.code, row.level): row
            for row in self.db.execute(select(models.UserAchievement).where(models.UserAchievement.user_id == user_id))
            .scalars()
            .all()
        }
        progress = {
            row.code: row.value
            for row in self.db.execute(
                select(models.UserAchievementProgress).where(models.UserAchievementProgress.user_id == user_id)
            )
            .scalars()
            .all()
        }

        views: list[AchievementView] = []
        for code in definitions.CODE_ORDER:
            for definition in definitions.levels_for(code):
                row = unlocked.get(definition.key)
                views.append(
                    AchievementView(
                        definition=definition,
                        unlocked=row is not None,
                        awarded_at=row.awarded_at if row is not None else None,
                        evidence=row.evidence if row is not None else None,
                        progress=progress.get(code) if row is None else None,
                    )
                )
        return views

    def count_unlocked(self, user_id: int) -> int:
        return len(
            self.db.execute(select(models.UserAchievement.id).where(models.UserAchievement.user_id == user_id))
            .scalars()
            .all()
        )

    def mark_notified(self, achievements: list[models.UserAchievement]) -> None:
        now = models.utc_now()
        for row in achievements:
            row.notified_at = now
        self.db.commit()

    def unnotified_for_tournament(self, tournament_id: int) -> list[models.UserAchievement]:
        return list(
            self.db.execute(
                select(models.UserAchievement).where(
                    models.UserAchievement.tournament_id == tournament_id,
                    models.UserAchievement.notified_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
