# Регистрация, выбор колоды — чистая бизнес-логика

from datetime import datetime, timedelta

from bot.features import FeatureService
from bot.handlers.base import HandlerResult
from bot.handlers.round_results import RoundResultsHandler
from bot.keyboards import Keyboards
from bot.messages import (
    ALREADY_REGISTERED,
    CHOOSE_ARCHETYPE,
    DEFER_DECK_EXPIRED,
    INVALID_FULL_NAME,
    LEAVE_CONFIRM_PROMPT,
    LEFT_TOURNAMENT,
    META_POLICE_ALL_FILLED,
    META_POLICE_DECK_ALREADY_FILLED,
    META_POLICE_FILL_UNAVAILABLE,
    NAME_REQUIRED_FOR_REGISTRATION,
    NO_ACTIVE_TOURNAMENTS,
    NOT_REGISTERED_IN_TOURNAMENT,
    PARTICIPANT_NOT_FOUND,
    REGISTERED,
    REGISTERED_AS,
    REGISTERED_DECK_LATER,
    REGISTRATION_CLOSED,
    SWISS_DROP_CONFIRM_PROMPT,
    SWISS_DROPPED,
    TOURNAMENT_NOT_FOUND,
    format_participant_name,
    format_tournament_card,
    format_tournament_status,
    format_unfilled_opponents_note,
    sort_participants,
)
from core import models
from services import errors
from services.aetherhub_import_service import AetherhubImportService
from services.archetype import ArchetypeItem, ArchetypeService
from services.names import has_complete_person_name, parse_full_name_input
from services.payment_service import PaymentService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament

ARCHETYPE_COLLAPSED_COUNT = 3
DEFER_DECK_WINDOW = timedelta(hours=7)


def _defer_deck_deadline(tournament) -> datetime:
    """Keep “choose later” available until start for tournaments opened in advance."""
    deadline = tournament.created_at + DEFER_DECK_WINDOW
    if tournament.registration_close_at is not None:
        deadline = max(deadline, tournament.registration_close_at)
    return deadline


def build_archetype_menu(
    arch_svc: "ArchetypeService",
    player_tg_id: int | None,
    expanded: bool = False,
) -> tuple[list[tuple[int, str]], bool]:
    """Общая логика сборки меню архетипов для любого игрока.

    Используется в PlayerHandler (флоу «Записаться») и AdminHandler
    (флоу «выбор колоды для участника»).

    Возвращает (arch_list, has_more), где arch_list = [(id, name), ...].
    """
    recent = arch_svc.list_user_recent_archetypes(player_tg_id) if player_tg_id is not None else []
    top = arch_svc.list_top_archetypes()
    archetypes, has_more = build_archetype_list(recent, top, expanded)
    return [(a.id, a.name) for a in archetypes], has_more


def build_archetype_list(
    recent: list[ArchetypeItem],
    top: list[ArchetypeItem],
    expanded: bool = False,
) -> tuple[list[ArchetypeItem], bool]:
    """Формирует список архетипов для отображения и флаг наличия кнопки «ещё».

    Правила:
    - Нет истории: показываем top, has_more=False.
    - Есть история, не развёрнуто: первые ARCHETYPE_COLLAPSED_COUNT из recent, has_more=True.
    - Есть история, развёрнуто: вся история + top без дублей (из истории), has_more=False.

    Аргументы:
        recent: история пользователя (самые свежие первыми, без дублей).
        top: топ-N архетипов по глобальной популярности.
        expanded: True если пользователь нажал «ещё».
    """
    if not recent:
        return list(top), False
    if not expanded:
        return list(recent[:ARCHETYPE_COLLAPSED_COUNT]), True
    history_ids = {a.id for a in recent}
    deduped_top = [a for a in top if a.id not in history_ids]
    return list(recent) + deduped_top, False


class PlayerHandler:
    def __init__(
        self,
        svc: TournamentService,
        user_svc: UserService,
        arch_svc: ArchetypeService,
        keyboards: Keyboards,
        aetherhub_svc: AetherhubImportService,
        feature_svc: FeatureService,
        payment_svc: PaymentService | None = None,
    ) -> None:
        self.svc = svc
        self.user_svc = user_svc
        self.arch_svc = arch_svc
        self.keyboards = keyboards
        self.aetherhub_svc = aetherhub_svc
        self.feature_svc = feature_svc
        self.payment_svc = payment_svc

    def _tournament_card(self, t, tg_id: int | None) -> HandlerResult:
        is_registered = False
        is_admin = False
        has_deck = True
        if tg_id is not None:
            user = self.user_svc.get_by_tg_id(tg_id)
            if user:
                participant = self.svc.get_participant(t.id, user.id)
                is_registered = participant is not None
                if participant is not None:
                    has_deck = participant.archetype_id is not None
            is_admin = self.user_svc.is_admin(tg_id)
        participants = self.svc.list_participants_for_tournament(t.id)
        with_deck = sum(1 for p in participants if p.archetype)
        has_pairings = self._has_pairings(t)
        show_fill_opponents = has_pairings and self.feature_svc.can_fill_opponent_decks()
        text = format_tournament_card(
            t.title,
            t.status.label_ru,
            total=len(participants),
            with_deck=with_deck,
        )
        payment_enabled = self.feature_svc.is_payment_enabled()
        payment_confirmed = (
            payment_enabled
            and is_registered
            and tg_id is not None
            and self.payment_svc is not None
            and self.payment_svc.is_paid(tg_id, t.id)
        )
        return HandlerResult(
            text,
            keyboard=self.keyboards.tournament_card_keyboard(
                t.id,
                is_registered,
                is_admin=is_admin,
                decks_hidden=t.decks_hidden,
                show_fill_opponents=show_fill_opponents,
                has_deck=has_deck,
                aetherhub_url=getattr(t, "aetherhub_url", None),
                import_time=getattr(t, "aetherhub_import_time", None),
                payment_enabled=payment_enabled,
                payment_confirmed=payment_confirmed,
                show_round_result_action=(t.is_online and has_pairings and t.status != models.TournamentStatus.CLOSED),
                internal_swiss=(t.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS),
            ),
        )

    def _archetype_keyboard_for_player(
        self, tournament_id: int, tg_id: int | None, expanded: bool = False
    ) -> HandlerResult:
        """Строит HandlerResult с клавиатурой архетипов для игрока."""
        tournament = get_tournament(self.svc.db, tournament_id)
        arch_list, has_more = build_archetype_menu(self.arch_svc, tg_id, expanded)
        user = self.user_svc.get_by_tg_id(tg_id) if tg_id else None
        show_emoji = not (user and user.hide_deck_emoji)
        can_defer = (
            tournament.status == models.TournamentStatus.REGISTRATION
            and models.utc_now() < _defer_deck_deadline(tournament)
        )
        return HandlerResult(
            CHOOSE_ARCHETYPE,
            keyboard=self.keyboards.archetype_keyboard(
                tournament_id,
                arch_list,
                has_more,
                show_emoji,
                can_defer,
            ),
        )

    def handle_tournaments(self, tg_id: int | None = None) -> HandlerResult:
        tournaments = self.svc.list_all_active_tournaments()
        if not tournaments:
            return HandlerResult(NO_ACTIVE_TOURNAMENTS)
        if len(tournaments) == 1:
            return self._tournament_card(tournaments[0], tg_id)
        tour_list = [(t.id, t.title) for t in tournaments]
        return HandlerResult("Выберите турнир:", keyboard=self.keyboards.tournament_list_keyboard(tour_list))

    def handle_tournament_select(self, tournament_id: int, tg_id: int | None = None) -> HandlerResult:
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return self._tournament_card(t, tg_id)

    def handle_register(self, tournament_id: int, tg_id: int | None = None) -> HandlerResult:
        """Возвращает выбор архетипа, запросив обязательные поля профиля."""
        if tg_id is not None:
            user = self.user_svc.get_by_tg_id(tg_id)
            if user is None or not has_complete_person_name(user.first_name, user.last_name):
                return HandlerResult(NAME_REQUIRED_FOR_REGISTRATION, needs_name=True)
        return self._archetype_keyboard_for_player(tournament_id, tg_id)

    def handle_deeplink_deck(self, tournament_id: int, tg_id: int) -> HandlerResult:
        """Диплинк в запись колоды на турнир (см. bot/deeplink.py).

        Регистрация ещё идёт и колоды нет (не записан или записан без колоды) → выбор
        архетипа. Уже с колодой или регистрация закрыта → карточка турнира (в ней виден
        статус). Турнира нет — сообщение об этом.
        """
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND)

        # Регистрация закрыта — не ведём в выбор архетипа (register_participant всё равно
        # бросил бы TournamentInvalidState). Показываем карточку со статусом.
        if tournament.status != models.TournamentStatus.REGISTRATION:
            return self.handle_tournament_select(tournament_id, tg_id=tg_id)

        user = self.user_svc.get_by_tg_id(tg_id)
        if user is not None:
            participant = self.svc.get_participant(tournament_id, user.id)
            if participant is not None and participant.archetype_id is not None:
                return self.handle_tournament_select(tournament_id, tg_id=tg_id)
        return self.handle_register(tournament_id, tg_id=tg_id)

    def handle_deeplink_registration(self, tournament_id: int, tg_id: int) -> HandlerResult:
        """Общая регистрация: новый игрок выбирает колоду, записанный видит статус."""
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND)

        user = self.user_svc.get_by_tg_id(tg_id)
        if user is not None and self.svc.get_participant(tournament_id, user.id) is not None:
            return self.handle_tournament_select(tournament_id, tg_id=tg_id)
        if tournament.status != models.TournamentStatus.REGISTRATION:
            return self.handle_tournament_select(tournament_id, tg_id=tg_id)
        return self.handle_register(tournament_id, tg_id=tg_id)

    def _meta_police_tournament(self, tournament_id: int):
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return None
        if (
            not self.feature_svc.can_fill_opponent_decks()
            or tournament.status == models.TournamentStatus.CLOSED
            or tournament.missing_decks_reminder_1d_sent_at is None
        ):
            return None
        return tournament

    def _unfilled_opponents_note(self, tournament_id: int, tg_id: int) -> str:
        user = self.user_svc.get_by_tg_id(tg_id)
        if user is None:
            return ""
        participants = self.svc.list_participants_for_tournament(tournament_id)
        opponents, error = self.aetherhub_svc.get_unfilled_opponents(
            tournament_id,
            user.id,
            participants,
        )
        return "" if error else format_unfilled_opponents_note(opponents)

    def _with_unfilled_opponents_note(self, text: str, tournament_id: int, tg_id: int) -> str:
        note = self._unfilled_opponents_note(tournament_id, tg_id)
        return f"{text}\n\n{note}" if note else text

    def _missing_decks_result(
        self,
        tournament_id: int,
        prefix: str | None = None,
        viewer_tg_id: int | None = None,
    ) -> HandlerResult:
        participants = self.svc.list_participants_for_tournament(tournament_id)
        missing = [participant for participant in participants if participant.archetype_id is None]
        if not missing:
            text = META_POLICE_ALL_FILLED
            return HandlerResult(f"{prefix}\n\n{text}" if prefix else text)
        text = "Выберите игрока без колоды:"
        if prefix:
            text = f"{prefix}\n\n{text}"
        if viewer_tg_id is not None:
            text = self._with_unfilled_opponents_note(text, tournament_id, viewer_tg_id)
        return HandlerResult(text, keyboard=self.keyboards.missing_decks_keyboard(missing))

    def _missing_deck_archetype_result(
        self, participant_id: int, caller_tg_id: int, expanded: bool = False
    ) -> HandlerResult:
        participant = self.svc.get_participant_by_id(participant_id)
        if participant is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if self._meta_police_tournament(participant.tournament_id) is None:
            return HandlerResult(META_POLICE_FILL_UNAVAILABLE, is_alert=True)
        if participant.archetype_id is not None:
            return HandlerResult(META_POLICE_DECK_ALREADY_FILLED, is_alert=True)

        target = self.user_svc.get_by_id(participant.user_id)
        target_tg_id = target.tg_id if target else None
        arch_list, has_more = build_archetype_menu(self.arch_svc, target_tg_id, expanded)
        caller = self.user_svc.get_by_tg_id(caller_tg_id)
        show_emoji = not (caller and caller.hide_deck_emoji)
        if target_tg_id == caller_tg_id:
            text = "Выберите свою колоду:"
        else:
            name = (
                format_participant_name(
                    target.first_name if target else None,
                    target.last_name if target else None,
                )
                or f"id{participant.id}"
            )
            text = f"Выберите колоду для {name}:"
        text = self._with_unfilled_opponents_note(text, participant.tournament_id, caller_tg_id)
        return HandlerResult(
            text,
            keyboard=self.keyboards.missing_deck_archetype_keyboard(
                participant_id,
                arch_list,
                has_more,
                show_emoji,
            ),
        )

    def handle_fill_missing_deeplink(self, tournament_id: int, tg_id: int) -> HandlerResult:
        """Вход по кнопке мета-полиции: сначала своя пустая колода, иначе общий список."""
        try:
            get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND)
        if self._meta_police_tournament(tournament_id) is None:
            return HandlerResult(META_POLICE_FILL_UNAVAILABLE)

        user = self.user_svc.get_by_tg_id(tg_id)
        if user is not None:
            own_participant = self.svc.get_participant(tournament_id, user.id)
            if own_participant is not None and own_participant.archetype_id is None:
                return self._missing_deck_archetype_result(own_participant.id, tg_id)
        return self._missing_decks_result(tournament_id, viewer_tg_id=tg_id)

    def handle_pick_missing_deck(self, tg_id: int, participant_id: int, expanded: bool = False) -> HandlerResult:
        return self._missing_deck_archetype_result(participant_id, tg_id, expanded)

    def handle_set_missing_deck(self, tg_id: int, participant_id: int, archetype_id: int) -> HandlerResult:
        participant = self.svc.get_participant_by_id(participant_id)
        if participant is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if self._meta_police_tournament(participant.tournament_id) is None:
            return HandlerResult(META_POLICE_FILL_UNAVAILABLE, is_alert=True)
        if participant.archetype_id is not None:
            return HandlerResult(META_POLICE_DECK_ALREADY_FILLED, is_alert=True)

        archetypes = {archetype.id: archetype.name for archetype in self.arch_svc.list_archetypes()}
        arch_name = archetypes.get(archetype_id)
        if arch_name is None:
            return HandlerResult("Архетип не найден.", is_alert=True)
        saved = self.svc.set_participant_archetype_if_missing(
            participant_id=participant_id,
            archetype_id=archetype_id,
            deck_added_by_tg_id=tg_id,
        )
        if saved is None:
            return HandlerResult(META_POLICE_DECK_ALREADY_FILLED, is_alert=True)

        target = self.user_svc.get_by_id(participant.user_id)
        name = (
            format_participant_name(
                target.first_name if target else None,
                target.last_name if target else None,
            )
            or f"id{participant.id}"
        )
        return self._missing_decks_result(
            participant.tournament_id,
            prefix=f"✅ {name} записан как {arch_name}.",
            viewer_tg_id=tg_id,
        )

    def handle_set_missing_custom_deck(self, tg_id: int, participant_id: int, arch_name: str) -> HandlerResult:
        participant = self.svc.get_participant_by_id(participant_id)
        if participant is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if self._meta_police_tournament(participant.tournament_id) is None:
            return HandlerResult(META_POLICE_FILL_UNAVAILABLE, is_alert=True)
        if participant.archetype_id is not None:
            return HandlerResult(META_POLICE_DECK_ALREADY_FILLED, is_alert=True)
        archetype = self.arch_svc.get_or_create_by_name(arch_name, is_custom=True)
        return self.handle_set_missing_deck(tg_id, participant_id, archetype.id)

    def handle_archetype_more(self, tournament_id: int, tg_id: int) -> HandlerResult:
        """Разворачивает полный список архетипов (история + топ)."""
        return self._archetype_keyboard_for_player(tournament_id, tg_id, expanded=True)

    def handle_save_name_then_register(
        self,
        tg_id: int,
        username: str | None,
        name_text: str,
        tournament_id: int,
    ) -> HandlerResult:
        """Сохраняет имя пользователя и возвращает выбор архетипа."""
        parsed = parse_full_name_input(name_text)
        if parsed is None:
            return HandlerResult(INVALID_FULL_NAME, needs_name=True)
        first_name, last_name = parsed
        self.user_svc.update_name(tg_id, first_name, last_name)
        self.user_svc.merge_placeholder_by_name(tg_id, first_name, last_name)
        return self.handle_register(tournament_id, tg_id)

    def _register_user(
        self, tg_id: int, username: str | None, first_name: str | None, last_name: str | None
    ) -> "models.User":
        """Находит/создаёт реального юзера и подтягивает его импортный placeholder-дубль.

        Слияние по имени нужно не только при вводе имени (см. handle_save_name_then_register),
        но и при обычной регистрации: возвращающийся игрок с уже сохранённым именем иначе
        оставил бы отдельным участником placeholder, заведённый импортом AetherHub раньше.
        """
        db_user = self.user_svc.get_or_create(
            tg_id=tg_id, username=username, first_name=first_name, last_name=last_name
        )
        fn, ln = db_user.first_name, db_user.last_name
        if fn or ln:
            self.user_svc.merge_placeholder_by_name(tg_id, fn or ln, ln if fn else None)
        return db_user

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
            db_user = self._register_user(tg_id, username, first_name, last_name)
            try:
                self.svc.register_participant(
                    tournament_id=tournament_id,
                    user_id=db_user.id,
                    archetype_id=archetype_id,
                    deck_added_by_tg_id=tg_id,
                )
            except errors.ParticipantAlreadyRegistered:
                participant = self.svc.get_participant(tournament_id, db_user.id)
                if participant is None or participant.archetype_id is not None:
                    return HandlerResult(ALREADY_REGISTERED, is_alert=True)
                self.svc.set_participant_archetype(
                    participant_id=participant.id,
                    archetype_id=archetype_id,
                    deck_added_by_tg_id=tg_id,
                )
            archetypes = {a.id: a.name for a in self.arch_svc.list_archetypes()}
            name = archetypes.get(archetype_id, "?")
            return HandlerResult(REGISTERED_AS.format(archetype_name=name))
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED, is_alert=True)

    def handle_defer_deck(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        tournament_id: int,
    ) -> HandlerResult:
        """Register without a deck during the first seven hours after tournament creation."""
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if tournament.status != models.TournamentStatus.REGISTRATION:
            return HandlerResult(REGISTRATION_CLOSED, is_alert=True)
        if models.utc_now() >= _defer_deck_deadline(tournament):
            return HandlerResult(DEFER_DECK_EXPIRED, is_alert=True)

        db_user = self._register_user(tg_id, username, first_name, last_name)
        try:
            self.svc.register_participant(
                tournament_id=tournament_id,
                user_id=db_user.id,
                deck_deferred=True,
            )
        except errors.ParticipantAlreadyRegistered:
            participant = self.svc.get_participant(tournament_id, db_user.id)
            if participant is None or participant.archetype_id is not None:
                return HandlerResult(ALREADY_REGISTERED, is_alert=True)
            self.svc.mark_participant_deck_deferred(participant.id)
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED, is_alert=True)
        return HandlerResult(REGISTERED_DECK_LATER)

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
            archetype = self.arch_svc.get_or_create_by_name(name, is_custom=True)
            db_user = self._register_user(tg_id, username, first_name, last_name)
            try:
                self.svc.register_participant(
                    tournament_id=tournament_id,
                    user_id=db_user.id,
                    archetype_id=archetype.id,
                    deck_added_by_tg_id=tg_id,
                )
            except errors.ParticipantAlreadyRegistered:
                participant = self.svc.get_participant(tournament_id, db_user.id)
                if participant is None or participant.archetype_id is not None:
                    return HandlerResult(ALREADY_REGISTERED)
                self.svc.set_participant_archetype(
                    participant_id=participant.id,
                    archetype_id=archetype.id,
                    deck_added_by_tg_id=tg_id,
                )
            return HandlerResult(REGISTERED)
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED)

    def handle_tournament_public_status(self, tournament_id: int, tg_id: int | None = None) -> HandlerResult:
        """Показывает список участников турнира (доступно всем игрокам)."""
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if t.show_round_pairings and self._has_pairings(t):
            return RoundResultsHandler(self.svc.db, self.keyboards).handle_round_status(tournament_id, tg_id)
        participants = sort_participants(self.svc.list_participants_for_tournament(tournament_id))
        text = format_tournament_status(t.title, t.status.label_ru, participants, decks_hidden=t.decks_hidden)
        return HandlerResult(text)

    def _has_pairings(self, tournament) -> bool:
        if self.aetherhub_svc.has_pairings(tournament.id):
            return True
        if tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS:
            return False
        return self.svc.db.query(models.RoundPairing.id).filter_by(tournament_id=tournament.id).first() is not None

    def handle_leave_tournament(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает подтверждение выхода из турнира."""
        user = self.user_svc.get_by_tg_id(tg_id)
        if user is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        participant = self.svc.get_participant(tournament_id, user.id)
        if participant is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        tournament = get_tournament(self.svc.db, tournament_id)
        if (
            tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
            and tournament.status == models.TournamentStatus.ONGOING
        ):
            return HandlerResult(
                SWISS_DROP_CONFIRM_PROMPT,
                keyboard=self.keyboards.swiss_drop_confirm_keyboard(tournament_id),
            )
        return HandlerResult(LEAVE_CONFIRM_PROMPT, keyboard=self.keyboards.leave_confirm_keyboard(tournament_id))

    def handle_leave_confirm(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Удаляет игрока из турнира после подтверждения."""
        user = self.user_svc.get_by_tg_id(tg_id)
        if user is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
            if (
                tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
                and tournament.status == models.TournamentStatus.ONGOING
            ):
                self.svc.drop_participant(tournament_id, user.id)
                return HandlerResult(SWISS_DROPPED)
            self.svc.unregister_participant(tournament_id, user.id)
            return HandlerResult(LEFT_TOURNAMENT)
        except errors.ParticipantNotFound:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
