"""Pure business flow for the debug-only internal Swiss simulator."""

from __future__ import annotations

from bot.handlers.base import HandlerResult
from bot.handlers.round_results import RoundResultsHandler
from bot.keyboards import (
    Keyboards,
)
from core import models
from core.config import settings
from services.debug_swiss import DebugSwissService
from services.round_results import RoundResultError

PANEL_TITLE = "🐞 Debug-симулятор Swiss"


class DebugSwissHandler:
    """Drives a fake internal-Swiss field through the real engine from the debug bot.

    Every action is gated twice: ``settings.DEBUG`` plus the admin check inside
    :class:`services.debug_swiss.DebugSwissService`, and the service itself refuses
    tournaments outside ``settings.chat_ids``. Fake players have negative ``tg_id``
    and ``added_by_admin=True``, so no DM path can reach a real account.
    """

    def __init__(self, db, keyboards: Keyboards | None = None) -> None:
        self.db = db
        self.keyboards = keyboards or Keyboards()
        self.service = DebugSwissService(db)
        self.rounds = RoundResultsHandler(db, self.keyboards)

    def handle_panel(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            status = self.service.status(tournament_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        planned = status.planned_rounds
        lines = [
            PANEL_TITLE,
            f"Турнир #{status.tournament_id}: {status.title}",
            f"Статус: {status.status} · игроков: {status.active_players}",
            f"Раундов: {status.round_number}/{planned} (Swiss {status.swiss_rounds} + плей-офф {status.playoff_size or 0})",
            "",
        ]
        if status.status == models.TournamentStatus.ONGOING.value and not status.can_autoplay:
            lines.append("Все раунды сыграны и засчитаны — заверши турнир кнопкой из меню админа.")
            lines.append("")
        lines.append("Фейковые игроки получают отрицательный tg_id, архетип и деклист — уведомления им уйти не могут.")
        return HandlerResult(
            "\n".join(lines),
            keyboard=self.keyboards.debug_swiss_panel_keyboard(
                tournament_id,
                active_players=status.active_players,
                round_number=status.round_number,
                planned_rounds=planned,
                is_ready=bool(status.can_autoplay),
                is_closed=status.status == models.TournamentStatus.CLOSED.value,
            ),
        )

    def handle_fill(self, tournament_id: int, admin_tg_id: int, players: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            result = self.service.fill_players(tournament_id, players)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        panel = self.handle_panel(tournament_id, admin_tg_id)
        panel.answer_text = f"Добавлено {result.added}. Всего игроков: {result.total}."
        return panel

    def handle_autoplay(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            step = self.service.autoplay_round(tournament_id, admin_tg_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        screen = self.rounds.handle_round_status(tournament_id, admin_tg_id, step.round_number)
        if screen.is_alert:
            return screen
        screen.answer_text = f"Раунд {step.round_number}/{step.planned_rounds}, матчей {step.matches}." + (
            f" Дозаполнено результатов: {step.completed_previous}." if step.completed_previous else ""
        )
        return screen

    def handle_run_all(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            run = self.service.autoplay_all(tournament_id, admin_tg_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        panel = self.handle_panel(tournament_id, admin_tg_id)
        panel.answer_text = (
            f"Сыграно и засчитано раундов: {run.played}/{run.planned}."
            + (f" Результатов последнего раунда: {run.last_round_scored}." if run.last_round_scored else "")
            + " Осталось завершить турнир."
        )
        return panel

    def _gate(self, tournament_id: int, admin_tg_id: int) -> HandlerResult | None:
        if not settings.DEBUG:
            return HandlerResult("Симулятор Swiss доступен только в debug-боте.", is_alert=True)
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult("Турнир не найден.", is_alert=True)
        if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            return HandlerResult("Симулятор работает только с турнирами внутреннего Swiss.", is_alert=True)
        return None

    # ------------------------------------------------------------ forced close

    def handle_close_prompt(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            status = self.service.status(tournament_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        planned = status.planned_rounds
        lines = [
            "🧹 Закрыть debug-турнир без всех раундов?",
            f"Турнир #{status.tournament_id}: {status.title}",
            f"Сыграно раундов: {status.round_number}/{planned}.",
            "",
            "Обычное закрытие требует сыграть и засчитать все раунды — для Swiss это "
            "правильно, но мешает перезапустить отладку. Принудительное закрытие освобождает "
            "слот клуба; места не расставляются.",
        ]
        return HandlerResult(
            "\n".join(lines),
            keyboard=self.keyboards.debug_swiss_force_close_keyboard(tournament_id),
        )

    def handle_force_close(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            closed = self.service.force_close(tournament_id, admin_tg_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        result = self.handle_panel(tournament_id, admin_tg_id)
        result.answer_text = f"Закрыт турнир #{closed.id}."
        return result

    def handle_close_all_prompt(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        active = self.service.active_club_tournaments()
        lines = [
            "🧹 Закрыть все активные турниры Endstep?",
            f"Открытых турниров клуба: {len(active)}.",
            "",
            "Нужно, когда клуб упёрся в лимит в два активных турнира и `swiss setup` "
            "отказывается создавать новый. Места по всем закрытым турнирам не расставляются.",
        ]
        for tournament in active:
            lines.append(f"• #{tournament.id} {tournament.title} [{tournament.status.value}]")
        return HandlerResult(
            "\n".join(lines),
            keyboard=self.keyboards.debug_swiss_force_close_keyboard(tournament_id, scope="club"),
        )

    def handle_force_close_all(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        gate = self._gate(tournament_id, admin_tg_id)
        if gate is not None:
            return gate
        try:
            closed = self.service.force_close_active(admin_tg_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        result = self.handle_panel(tournament_id, admin_tg_id)
        result.answer_text = f"Закрыто турниров: {len(closed)}. Слоты клуба свободны."
        return result
