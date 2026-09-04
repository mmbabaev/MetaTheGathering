"""Pure Telegram-facing business flow for online round results."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardMarkup

from bot.handlers.base import HandlerResult
from bot.keyboards import (
    CB_ROUND_ADMIN,
    CB_ROUND_ADMIN_MATCH,
    CB_ROUND_ADMIN_P1,
    CB_ROUND_ADMIN_P2,
    CB_ROUND_RESULT_OPEN,
    CB_ROUND_RESULT_OPPONENT,
    CB_ROUND_RESULT_OWN,
    CB_ROUND_VIEW,
    Keyboards,
)
from bot.messages import format_aetherhub_round_summary, format_round_pairings, format_swiss_standings
from core import models
from core.config import settings
from services.internal_swiss import InternalSwissService
from services.round_results import FINAL_STATUSES, RoundResultError, RoundResultsService
from services.user import UserService


@dataclass(frozen=True)
class DeliveryResult:
    screen: HandlerResult
    recipient_tg_id: int | None = None
    recipient_text: str | None = None
    recipient_keyboard: InlineKeyboardMarkup | None = None
    tournament_id: int | None = None
    round_number: int | None = None


class RoundResultsHandler:
    def __init__(self, db, keyboards: Keyboards | None = None) -> None:
        self.db = db
        self.results = RoundResultsService(db)
        self.users = UserService(db)
        self.keyboards = keyboards or Keyboards()

    def handle_round_status(
        self, tournament_id: int, tg_id: int | None, round_number: int | None = None
    ) -> HandlerResult:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult("Турнир не найден.", is_alert=True)
        available = self._round_numbers(tournament_id)
        selected = round_number if round_number in available else (available[-1] if available else None)
        if selected is None:
            return HandlerResult("Паринги ещё не загружены.", is_alert=True)
        matches = self.results.list_round(tournament_id, selected)
        user = self.users.get_by_tg_id(tg_id) if tg_id is not None else None
        can_report = bool(
            user
            and selected == available[-1]
            and any(
                match.player2_name is not None and user.id in (match.player1_user_id, match.player2_user_id)
                for match in matches
            )
        )
        is_admin = bool(tg_id is not None and self.users.is_admin(tg_id))
        internal_swiss = tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
        round_ready = (
            self.results.is_round_ready(tournament_id, selected)
            if internal_swiss and selected == available[-1]
            else False
        )
        return HandlerResult(
            format_round_pairings(
                tournament.title,
                tournament.status.label_ru,
                selected,
                matches,
                planned_rounds=tournament.swiss_rounds if internal_swiss else None,
            ),
            keyboard=self.keyboards.round_status_keyboard(
                tournament_id,
                selected,
                available,
                can_report=can_report,
                is_admin=is_admin,
                show_debug_next=settings.DEBUG and is_admin,
                internal_swiss=internal_swiss,
                planned_rounds=tournament.swiss_rounds,
                round_ready=round_ready,
            ),
            parse_mode="HTML",
        )

    def handle_open(self, tournament_id: int, tg_id: int) -> HandlerResult:
        try:
            match = self.results.current_match_for_user(tournament_id, tg_id)
            actor = self.users.get_by_tg_id(tg_id)
            if actor is None:
                raise RoundResultError("Пользователь не найден.")
            if match.player2_name is None:
                return HandlerResult(f"Раунд {match.round_number}: у вас BYE. Результат вводить не нужно.")
            if match.status in FINAL_STATUSES:
                return HandlerResult(f"✅ Результат уже подтверждён:\n\n{self._score(match)}")
            if match.status == models.RoundMatchStatus.PENDING:
                if match.proposed_by_user_id == actor.id:
                    return HandlerResult(f"⏳ {self._score(match)}\n\nОжидаем подтверждения соперника.")
                return HandlerResult(
                    self._confirmation_text(match),
                    keyboard=self.keyboards.round_result_response_keyboard(
                        match.id,
                        match.revision,
                        back_callback_data=f"{CB_ROUND_VIEW}:{match.tournament_id}:{match.round_number}",
                    ),
                )
            own_name, opponent_name = self._actor_names(match, actor.id)
            return HandlerResult(
                f"Раунд {match.round_number} · {own_name} против {opponent_name}\n\nСколько игр выиграли вы?",
                keyboard=self.keyboards.round_score_values_keyboard(
                    match.id,
                    prefix=CB_ROUND_RESULT_OWN,
                    back_callback_data=f"{CB_ROUND_VIEW}:{match.tournament_id}:{match.round_number}",
                ),
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_own_wins(self, match_id: int, tg_id: int, own_wins: int) -> HandlerResult:
        try:
            match, actor = self._actor_match(match_id, tg_id)
            self.results.score_from_actor(match, actor.id, own_wins, 0)
            _own_name, opponent_name = self._actor_names(match, actor.id)
            return HandlerResult(
                f"Вы выиграли {own_wins}.\nСколько игр выиграл {opponent_name}?",
                keyboard=self.keyboards.round_score_values_keyboard(
                    match.id,
                    prefix=CB_ROUND_RESULT_OPPONENT,
                    extra=str(own_wins),
                    allow_two=own_wins != 2,
                    back_callback_data=f"{CB_ROUND_RESULT_OPEN}:{match.tournament_id}",
                ),
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_opponent_wins(self, match_id: int, tg_id: int, own_wins: int, opponent_wins: int) -> HandlerResult:
        try:
            match, actor = self._actor_match(match_id, tg_id)
            p1_wins, p2_wins = self.results.score_from_actor(match, actor.id, own_wins, opponent_wins)
            return HandlerResult(
                f"Вы указали:\n\n{self._score_values(match, p1_wins, p2_wins)}\n\nПередать сопернику на подтверждение?",
                keyboard=self.keyboards.round_result_preview_keyboard(match.id, own_wins, opponent_wins),
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_send(self, match_id: int, tg_id: int, own_wins: int, opponent_wins: int) -> DeliveryResult:
        try:
            match = self.results.propose(match_id, tg_id, own_wins, opponent_wins)
            actor = self.users.get_by_tg_id(tg_id)
            opponent = self._other_user(match, actor.id if actor else None)
            return DeliveryResult(
                screen=HandlerResult(f"⏳ {self._score(match)}\n\nРезультат ожидает подтверждения соперника."),
                recipient_tg_id=opponent.tg_id if opponent and opponent.tg_id > 0 else None,
                recipient_text=self._confirmation_text(match),
                recipient_keyboard=self.keyboards.round_result_response_keyboard(
                    match.id,
                    match.revision,
                    back_callback_data=f"{CB_ROUND_VIEW}:{match.tournament_id}:{match.round_number}",
                ),
                tournament_id=match.tournament_id,
                round_number=match.round_number,
            )
        except RoundResultError as exc:
            return DeliveryResult(screen=HandlerResult(str(exc), is_alert=True))

    def handle_confirm(self, match_id: int, revision: int, tg_id: int) -> DeliveryResult:
        try:
            match = self.results.confirm(match_id, revision, tg_id)
            proposer = self.db.get(models.User, match.proposed_by_user_id) if match.proposed_by_user_id else None
            return DeliveryResult(
                screen=HandlerResult(f"✅ Результат подтверждён:\n\n{self._score(match)}"),
                recipient_tg_id=proposer.tg_id if proposer and proposer.tg_id > 0 else None,
                recipient_text=f"✅ Соперник подтвердил результат:\n\n{self._score(match)}",
                tournament_id=match.tournament_id,
                round_number=match.round_number,
            )
        except RoundResultError as exc:
            return DeliveryResult(screen=HandlerResult(str(exc), is_alert=True))

    def handle_reject(self, match_id: int, revision: int, tg_id: int) -> DeliveryResult:
        try:
            rejected = self.results.reject(match_id, revision, tg_id)
            match = rejected.match
            actor = self.users.get_by_tg_id(tg_id)
            if actor is None:
                raise RoundResultError("Пользователь не найден.")
            own_name, opponent_name = self._actor_names(match, actor.id)
            return DeliveryResult(
                screen=HandlerResult(
                    f"Результат отклонён. Укажите правильный.\n\n"
                    f"Раунд {match.round_number} · {own_name} против {opponent_name}\n\n"
                    "Сколько игр выиграли вы?",
                    keyboard=self.keyboards.round_score_values_keyboard(
                        match.id,
                        prefix=CB_ROUND_RESULT_OWN,
                        back_callback_data=f"{CB_ROUND_VIEW}:{match.tournament_id}:{match.round_number}",
                    ),
                ),
                recipient_tg_id=rejected.proposer_tg_id,
                recipient_text=f"❌ Соперник отклонил предложенный результат раунда {match.round_number}.",
                tournament_id=match.tournament_id,
                round_number=match.round_number,
            )
        except RoundResultError as exc:
            return DeliveryResult(screen=HandlerResult(str(exc), is_alert=True))

    def handle_admin_list(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        if not self.users.is_admin(admin_tg_id):
            return HandlerResult("Нет прав администратора.", is_alert=True)
        round_number = self.results.latest_round_number(tournament_id)
        if round_number is None:
            return HandlerResult("Паринги ещё не загружены.", is_alert=True)
        matches = self.results.list_round(tournament_id, round_number)
        return HandlerResult(
            f"✏️ Результаты раунда {round_number}\n\nВыберите стол:",
            keyboard=self.keyboards.round_admin_matches_keyboard(tournament_id, matches),
        )

    def handle_admin_match(self, match_id: int, admin_tg_id: int) -> HandlerResult:
        if not self.users.is_admin(admin_tg_id):
            return HandlerResult("Нет прав администратора.", is_alert=True)
        try:
            match = self.results.get_match(match_id)
            return HandlerResult(
                f"{match.player1_name} против {match.player2_name}\n\nСколько выиграл {match.player1_name}?",
                keyboard=self.keyboards.round_score_values_keyboard(
                    match.id,
                    prefix=CB_ROUND_ADMIN_P1,
                    back_callback_data=f"{CB_ROUND_ADMIN}:{match.tournament_id}",
                ),
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_admin_p1(self, match_id: int, admin_tg_id: int, player1_wins: int) -> HandlerResult:
        if not self.users.is_admin(admin_tg_id):
            return HandlerResult("Нет прав администратора.", is_alert=True)
        try:
            match = self.results.get_match(match_id)
            return HandlerResult(
                f"{match.player1_name} выиграл {player1_wins}.\nСколько выиграл {match.player2_name}?",
                keyboard=self.keyboards.round_score_values_keyboard(
                    match.id,
                    prefix=CB_ROUND_ADMIN_P2,
                    extra=str(player1_wins),
                    allow_two=player1_wins != 2,
                    back_callback_data=f"{CB_ROUND_ADMIN_MATCH}:{match.id}",
                ),
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_admin_p2(self, match_id: int, admin_tg_id: int, player1_wins: int, player2_wins: int) -> HandlerResult:
        try:
            match = self.results.admin_set(match_id, admin_tg_id, player1_wins, player2_wins)
            result = self.handle_admin_list(match.tournament_id, admin_tg_id)
            result.answer_text = f"Сохранено: {self._score(match)}"
            result.tournament_id = match.tournament_id
            return result
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_summary(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        if not self.users.is_admin(admin_tg_id):
            return HandlerResult("Нет прав администратора.", is_alert=True)
        round_number = self.results.latest_round_number(tournament_id)
        if round_number is None:
            return HandlerResult("Паринги ещё не загружены.", is_alert=True)
        matches = self.results.list_round(tournament_id, round_number)
        return HandlerResult(
            format_aetherhub_round_summary(round_number, matches),
            keyboard=self.keyboards.round_summary_keyboard(tournament_id),
        )

    def handle_toggle_view(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        try:
            enabled = self.results.set_pairings_view(tournament_id, admin_tg_id)
            label = "паринги текущего раунда" if enabled else "список игроков"
            return HandlerResult(f"Вид статуса турнира: {label}.", answer_text=f"Статус: {label}")
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_swiss_toggle(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult("Турнир не найден.", is_alert=True)
        enabled = tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS
        try:
            updated = InternalSwissService(self.db).set_enabled(tournament_id, admin_tg_id, enabled)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        label = "внутренний Swiss" if updated.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS else "AetherHub"
        return HandlerResult(f"Движок турнира: {label}.", answer_text=f"Движок: {label}")

    def handle_swiss_next_round(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        try:
            generated = InternalSwissService(self.db).generate_next_round(tournament_id, admin_tg_id)
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)
        screen = self.handle_round_status(tournament_id, admin_tg_id, generated.round_number)
        screen.answer_text = f"Создан раунд {generated.round_number}/{generated.planned_rounds}."
        screen.new_round_numbers = [generated.round_number]
        return screen

    def handle_swiss_standings(self, tournament_id: int, tg_id: int, page: int = 0) -> HandlerResult:
        try:
            tournament = self.db.get(models.Tournament, tournament_id)
            if tournament is None:
                raise RoundResultError("Турнир не найден.")
            if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
                raise RoundResultError("Для этого турнира используются стендинги AetherHub.")
            engine = InternalSwissService(self.db)
            standings = engine.standings(tournament_id)
            round_number = self.results.latest_round_number(tournament_id) or 0
            planned = tournament.swiss_rounds or 0
            ready = bool(round_number and self.results.is_round_ready(tournament_id, round_number))
            page_count = max(1, (len(standings) + 19) // 20)
            page = max(0, min(page, page_count - 1))
            return HandlerResult(
                format_swiss_standings(
                    tournament.title,
                    round_number,
                    planned,
                    standings,
                    provisional=not ready,
                    page=page,
                ),
                keyboard=self.keyboards.swiss_standings_keyboard(
                    tournament_id, round_number, page=page, page_count=page_count
                ),
                parse_mode="HTML",
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def handle_swiss_finish_prompt(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        if not self.users.is_admin(admin_tg_id):
            return HandlerResult("Нет прав администратора.", is_alert=True)
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None or tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            return HandlerResult("Внутренний Swiss-турнир не найден.", is_alert=True)
        round_number = self.results.latest_round_number(tournament_id)
        if round_number is None or round_number < (tournament.swiss_rounds or 0):
            return HandlerResult(f"Сыграно раундов: {round_number or 0}/{tournament.swiss_rounds or 0}.", is_alert=True)
        if not self.results.is_round_ready(tournament_id, round_number):
            return HandlerResult(f"Сначала соберите все результаты раунда {round_number}.", is_alert=True)
        return HandlerResult(
            f"🏁 Завершить турнир «{tournament.title}» и зафиксировать итоговые места?",
            keyboard=self.keyboards.swiss_finish_confirm_keyboard(tournament_id),
        )

    def handle_swiss_finish(self, tournament_id: int, admin_tg_id: int) -> HandlerResult:
        try:
            standings = InternalSwissService(self.db).finish(tournament_id, admin_tg_id)
            tournament = self.db.get(models.Tournament, tournament_id)
            page_count = max(1, (len(standings) + 19) // 20)
            return HandlerResult(
                format_swiss_standings(
                    tournament.title,
                    tournament.swiss_rounds or 0,
                    tournament.swiss_rounds or 0,
                    standings,
                    provisional=False,
                ),
                keyboard=self.keyboards.swiss_standings_keyboard(
                    tournament_id, tournament.swiss_rounds, page_count=page_count
                ),
                parse_mode="HTML",
                answer_text="Турнир завершён.",
            )
        except RoundResultError as exc:
            return HandlerResult(str(exc), is_alert=True)

    def _round_numbers(self, tournament_id: int) -> list[int]:
        return list(
            self.db.execute(
                models.RoundPairing.__table__.select()
                .with_only_columns(models.RoundPairing.round_number)
                .where(models.RoundPairing.tournament_id == tournament_id)
                .distinct()
                .order_by(models.RoundPairing.round_number)
            ).scalars()
        )

    def _actor_match(self, match_id: int, tg_id: int) -> tuple[models.RoundMatch, models.User]:
        actor = self.users.get_by_tg_id(tg_id)
        if actor is None:
            raise RoundResultError("Пользователь не найден.")
        match = self.results.get_match(match_id)
        if actor.id not in (match.player1_user_id, match.player2_user_id):
            raise RoundResultError("Этот матч не принадлежит вам.")
        return match, actor

    @staticmethod
    def _score(match: models.RoundMatch) -> str:
        return RoundResultsHandler._score_values(match, match.player1_wins, match.player2_wins)

    @staticmethod
    def _score_values(match: models.RoundMatch, player1_wins: int, player2_wins: int) -> str:
        return f"{match.player1_name} {player1_wins}–{player2_wins} {match.player2_name}"

    @staticmethod
    def _actor_names(match: models.RoundMatch, actor_user_id: int) -> tuple[str, str]:
        if actor_user_id == match.player1_user_id:
            return match.player1_name, match.player2_name
        if actor_user_id == match.player2_user_id:
            return match.player2_name, match.player1_name
        raise RoundResultError("Этот матч не принадлежит вам.")

    @staticmethod
    def _other_user(match: models.RoundMatch, actor_user_id: int | None) -> models.User | None:
        if actor_user_id == match.player1_user_id:
            return match.player2_user
        if actor_user_id == match.player2_user_id:
            return match.player1_user
        return None

    def _confirmation_text(self, match: models.RoundMatch) -> str:
        proposer = self.db.get(models.User, match.proposed_by_user_id) if match.proposed_by_user_id else None
        proposer_name = "Соперник"
        if proposer is not None:
            proposer_name = proposer.last_name or proposer.first_name or proposer.username or proposer_name
        return (
            f"{proposer_name} указал результат раунда {match.round_number}:\n\n"
            f"{self._score(match)}\n\nРезультат верный?"
        )
