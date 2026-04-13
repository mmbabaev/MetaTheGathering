# Регистрация, выбор колоды — чистая бизнес-логика

from services.tournament import TournamentService
from services.user import UserService
from services import errors
from services.utils import get_tournament
from bot.handlers.base import HandlerResult
from bot.keyboards import (
    tournament_list_keyboard,
    tournament_card_keyboard,
    archetype_keyboard,
    leave_confirm_keyboard,
)
from bot.messages import (
    NO_ACTIVE_TOURNAMENTS,
    CHOOSE_ARCHETYPE,
    REGISTERED_AS,
    REGISTERED,
    ALREADY_REGISTERED,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
    NAME_REQUIRED_FOR_REGISTRATION,
    LEAVE_CONFIRM_PROMPT,
    LEFT_TOURNAMENT,
    NOT_REGISTERED_IN_TOURNAMENT,
    format_tournament_card,
    format_tournament_status,
)


class PlayerHandler:
    def __init__(self, svc: TournamentService, user_svc: UserService) -> None:
        self.svc = svc
        self.user_svc = user_svc

    def _tournament_card(self, t, tg_id: int | None) -> HandlerResult:
        is_registered = False
        if tg_id is not None:
            user = self.user_svc.get_by_tg_id(tg_id)
            if user:
                is_registered = self.svc.get_participant(t.id, user.id) is not None
        text = format_tournament_card(t.title, t.status.label_ru, t.slug)
        return HandlerResult(text, keyboard=tournament_card_keyboard(t.id, is_registered))

    def handle_tournaments(self, tg_id: int | None = None) -> HandlerResult:
        tournaments = self.svc.list_all_active_tournaments()
        if not tournaments:
            return HandlerResult(NO_ACTIVE_TOURNAMENTS)
        if len(tournaments) == 1:
            return self._tournament_card(tournaments[0], tg_id)
        tour_list = [(t.id, t.title) for t in tournaments]
        return HandlerResult("Выберите турнир:", keyboard=tournament_list_keyboard(tour_list))

    def handle_tournament_select(
        self, tournament_id: int, tg_id: int | None = None
    ) -> HandlerResult:
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return self._tournament_card(t, tg_id)

    def handle_register(
        self, tournament_id: int, tg_id: int | None = None
    ) -> HandlerResult:
        """Возвращает выбор архетипа. Если имя не задано — needs_name=True."""
        if tg_id is not None:
            user = self.user_svc.get_by_tg_id(tg_id)
            if user is None or not user.first_name:
                return HandlerResult(NAME_REQUIRED_FOR_REGISTRATION, needs_name=True)
            archetypes = self.svc.list_archetypes_for_user(tg_id)
        else:
            archetypes = self.svc.list_archetypes()[:10]
        arch_list = [(a.id, a.name) for a in archetypes]
        return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))

    def handle_save_name_then_register(
        self,
        tg_id: int,
        username: str | None,
        name_text: str,
        tournament_id: int,
    ) -> HandlerResult:
        """Сохраняет имя пользователя и возвращает выбор архетипа."""
        parts = name_text.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None
        self.user_svc.update_name(tg_id, first_name, last_name)
        archetypes = self.svc.list_archetypes_for_user(tg_id)
        arch_list = [(a.id, a.name) for a in archetypes]
        return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))

    def handle_archetype(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        tournament_id: int,
        archetype_id: int,
    ) -> HandlerResult:
        try:
            db_user = self.user_svc.get_or_create(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            self.svc.register_participant(
                tournament_id=tournament_id,
                user_id=db_user.id,
                archetype_id=archetype_id,
            )
            archetypes = {a.id: a.name for a in self.svc.list_archetypes()}
            name = archetypes.get(archetype_id, "?")
            return HandlerResult(REGISTERED_AS.format(archetype_name=name))
        except errors.ParticipantAlreadyRegistered:
            return HandlerResult(ALREADY_REGISTERED, is_alert=True)
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED, is_alert=True)

    def handle_custom_archetype_text(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        tournament_id: int,
        name: str,
    ) -> HandlerResult:
        try:
            archetype = self.svc.get_or_create_archetype_by_name(name)
            db_user = self.user_svc.get_or_create(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            self.svc.register_participant(
                tournament_id=tournament_id,
                user_id=db_user.id,
                archetype_id=archetype.id,
            )
            return HandlerResult(REGISTERED)
        except errors.ParticipantAlreadyRegistered:
            return HandlerResult(ALREADY_REGISTERED)
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED)

    def handle_tournament_public_status(self, tournament_id: int) -> HandlerResult:
        """Показывает список участников турнира (доступно всем игрокам)."""
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        participants = self.svc.list_participants_for_tournament(tournament_id)
        text = format_tournament_status(t.title, t.status.label_ru, participants)
        return HandlerResult(text)

    def handle_leave_tournament(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает подтверждение выхода из турнира."""
        user = self.user_svc.get_by_tg_id(tg_id)
        if user is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        participant = self.svc.get_participant(tournament_id, user.id)
        if participant is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        return HandlerResult(LEAVE_CONFIRM_PROMPT, keyboard=leave_confirm_keyboard(tournament_id))

    def handle_leave_confirm(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Удаляет игрока из турнира после подтверждения."""
        user = self.user_svc.get_by_tg_id(tg_id)
        if user is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        try:
            self.svc.unregister_participant(tournament_id, user.id)
            return HandlerResult(LEFT_TOURNAMENT)
        except errors.ParticipantNotFound:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
