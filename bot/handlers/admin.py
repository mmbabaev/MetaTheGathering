# Админ-панель — чистая бизнес-логика

import re
from datetime import datetime

from bot.features import FeatureService
from bot.handlers.base import HandlerResult
from bot.handlers.player import build_archetype_menu
from bot.handlers.round_results import RoundResultsHandler
from bot.handlers.tournament_status import pairing_rows
from bot.keyboards import Keyboards, broadcast_confirm_keyboard, broadcast_input_keyboard
from bot.messages import (
    ADMIN_ARCH_SAVED,
    BROADCAST_NO_RECIPIENTS,
    BROADCAST_OWNER_ONLY,
    BROADCAST_PROMPT,
    BROADCAST_TOO_LONG,
    BULK_ADD_EMPTY,
    CHOOSE_ARCHETYPE,
    DECKS_REVEALED,
    META_IMPORT_PROMPT,
    MULTIPLE_TOURNAMENTS_MSG,
    NO_ACTIVE_TOURNAMENT,
    NOT_ADMIN,
    NOT_REGISTERED_IN_TOURNAMENT,
    PARTICIPANT_NOT_FOUND,
    POLL_ORGANIZER_GRANTED,
    POLL_ORGANIZER_REVOKED,
    REGISTRATION_CLOSED,
    SCOREKEEPER_GRANTED,
    SCOREKEEPER_REVOKED,
    TOURNAMENT_ALREADY_EXISTS_MSG,
    TOURNAMENT_CLOSED_MSG,
    TOURNAMENT_NOT_FOUND,
    clamp_page,
    format_broadcast_preview,
    format_participant_name,
    format_tournament_status,
    page_bounds,
    page_count,
    participant_page_for_tg_id,
    prepend_note,
    sort_participants,
)
from core import models
from core.config import settings
from core.schemas import TournamentCreate
from services import errors
from services.aetherhub_import_service import MIN_TOURNAMENT_DURATION, AetherhubImportService
from services.archetype import ArchetypeService
from services.decklists import DecklistService
from services.endstep_table_titles import is_konetskhod_club, konetskhod_title
from services.export import ExportService
from services.internal_swiss import InternalSwissService
from services.meta_table_import import MetaTableImportService
from services.poll import PollService
from services.ranked_activation import RANKED_ACTIVATION_SELF_BOT
from services.round_results import RoundResultError
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament

ENDSTEP_IDENTITY_PAGE_SIZE = 50


def parse_bulk_player_line(line: str) -> tuple[str, str] | None:
    """Строка «@user Колода» → (username_без_собаки, колода). Неверная строка → None."""
    text = re.sub(r"\s+", " ", line.strip())
    if not text:
        return None
    parts = text.split(None, 1)
    if len(parts) < 2:
        return None
    return (parts[0].lstrip("@"), parts[1].strip())


def _player_display_label(username: str | None, first_name: str | None, tg_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return f"игрок {tg_id}"


# Telegram не примет сообщение длиннее 4096 символов; берём запас под оформление отчёта.
BROADCAST_MAX_LENGTH = 4000


class AdminHandler:
    def __init__(
        self,
        svc: TournamentService,
        user_svc: UserService,
        arch_svc: ArchetypeService,
        keyboards: Keyboards,
        features: FeatureService,
    ) -> None:
        self.svc = svc
        self.user_svc = user_svc
        self.arch_svc = arch_svc
        self.keyboards = keyboards
        self._features = features

    def _resolve_tournament(self):
        """Возвращает (tournament, error_result). Один из них None."""
        try:
            return self.svc.get_single_active_tournament(), None
        except errors.TournamentNotFound:
            return None, HandlerResult(NO_ACTIVE_TOURNAMENT)
        except errors.MultipleActiveTournaments:
            return None, HandlerResult(MULTIPLE_TOURNAMENTS_MSG)

    def _is_privileged_for_tournament(self, tg_id: int, tournament_id: int) -> bool:
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        return bool(tournament and self.user_svc.is_privileged_for_tournament(tg_id, tournament))

    def handle_add_players(
        self,
        tg_id: int,
        entries: list[tuple[int, str | None, str | None, str]],
    ) -> HandlerResult:
        """entries: (target_tg_id, username, first_name, deck_name) — после резолва в Telegram."""
        if not self.user_svc.is_privileged(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not entries:
            return HandlerResult("Нет данных для обработки.")
        active, err = self._resolve_tournament()
        if err:
            return err
        if not self.user_svc.is_privileged_for_tournament(tg_id, active):
            return HandlerResult(NOT_ADMIN)
        results = []
        for target_tg_id, uname, fname, deck_name in entries:
            user_label = _player_display_label(uname, fname, target_tg_id)
            try:
                target_user = self.user_svc.get_or_create(
                    tg_id=target_tg_id,
                    username=uname,
                    first_name=fname,
                )
                archetype = self.arch_svc.get_or_create_by_name(deck_name)
                self.svc.register_participant(
                    tournament_id=active.id,
                    user_id=target_user.id,
                    archetype_id=archetype.id,
                    added_by_admin=True,
                    deck_added_by_tg_id=tg_id,
                )
                results.append(f"✅ {user_label} — {archetype.name}")
            except errors.ParticipantAlreadyRegistered:
                results.append(f"⚠️ {user_label} — уже записан")
            except errors.TournamentInvalidState:
                results.append(f"❌ {user_label} — регистрация закрыта")
        return HandlerResult("\n".join(results) if results else "Нет данных для обработки.")

    def handle_bulk_add_by_name(
        self,
        tg_id: int,
        tournament_id: int,
        names: list[str],
    ) -> HandlerResult:
        """Массово добавить игроков по имени без архетипа.

        names: список строк вида «Имя» или «Имя Фамилия».
        Игроки ищутся в БД по имени; если не найдены — создаются с placeholder tg_id.
        Уже зарегистрированные пропускаются.
        """
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult(TOURNAMENT_NOT_FOUND)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN)

        parsed: list[tuple[str, str | None]] = []
        for raw in names:
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split(None, 1)
            # Input format: "Фамилия Имя" — first word is last_name, second is first_name
            if len(parts) == 2:
                parsed.append((parts[1], parts[0]))  # (first_name, last_name)
            else:
                parsed.append((parts[0], None))

        if not parsed:
            return HandlerResult(BULK_ADD_EMPTY)

        entries: list[tuple[int, str]] = []
        for first_name, last_name in parsed:
            user, _ = self.user_svc.get_or_create_by_name(first_name, last_name)
            display = f"{last_name} {first_name}" if last_name else first_name
            if user.username:
                display += f" (@{user.username})"
            entries.append((user.id, display))

        try:
            results = self.svc.bulk_add_participants(tournament_id, entries)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND)
        except errors.TournamentInvalidState:
            return HandlerResult(REGISTRATION_CLOSED)

        lines = []
        for display_name, status in results:
            if status == "added":
                lines.append(f"✅ {display_name}")
            else:
                lines.append(f"⚠️ {display_name} — уже записан")
        return self._tournament_status_result(tournament_id, prefix="\n".join(lines), tg_id=tg_id)

    def _tournament_status_result(
        self,
        tournament_id: int,
        prefix: str = "",
        show_filled: bool = False,
        tg_id: int = 0,
        page: int = 0,
        highlight_tg_id: int | None = None,
    ) -> HandlerResult:
        """Строит HandlerResult со статусом турнира и клавиатурой участников.

        prefix — необязательный текст (например, итог операции), который добавляется
        перед статусом через пустую строку.
        show_filled — показывать заполненных участников или полностью заполненные столы.
        tg_id — кто смотрит: если включена настройка «статус по парингам» и паринги
        есть, кнопки участников раскладываются по столам (две кнопки в ряд).
        page — номер страницы списка участников; текст и кнопки всегда описывают
        один и тот же срез, чтобы «1–50» в тексте совпадало с кнопками под ним.
        """
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if t.status == models.TournamentStatus.CLOSED and t.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS:
            players = DecklistService(self.svc.db).list_players(tournament_id, tg_id)
            text = "Деклисты игроков:\n✅ — деклист загружен, — — деклиста пока нет."
            if prefix:
                text = prepend_note(text, prefix)
            return HandlerResult(
                text,
                keyboard=self.keyboards.decklist_players_keyboard(tournament_id, players),
            )
        if t.show_round_pairings and AetherhubImportService(self.svc.db).has_pairings(tournament_id):
            result = RoundResultsHandler(self.svc.db, self.keyboards).handle_round_status(tournament_id, tg_id)
            if prefix and not result.is_alert:
                result.text = prepend_note(result.text, prefix)
            return result
        participants = sort_participants(self.svc.list_participants_for_tournament(tournament_id))
        total = len(participants)
        page = clamp_page(page, total)
        start, end = page_bounds(page, total)
        shown = participants[start:end]
        body = format_tournament_status(
            t.title,
            t.status.label_ru,
            shown,
            decks_hidden=t.decks_hidden,
            total=total,
            with_deck=sum(1 for p in participants if p.archetype),
            page=page,
            highlight_tg_id=highlight_tg_id,
        )
        text = prepend_note(body, prefix) if prefix else body

        pairs = unpaired = None
        if self.user_svc.wants_status_by_pairings(tg_id):
            resolved = pairing_rows(self.svc.db, tournament_id, participants)
            if resolved is not None:
                pairs, unpaired = resolved
        return HandlerResult(
            text,
            keyboard=self.keyboards.admin_participants_keyboard(
                shown,
                tournament_id=tournament_id,
                show_filled=show_filled,
                pairs=pairs,
                unpaired=unpaired,
                page=page,
                total=total,
                show_me=tg_id > 0 and participant_page_for_tg_id(participants, tg_id) is not None,
            ),
        )

    def handle_admin_status(self, tg_id: int, tournament_id: int, page: int = 0) -> HandlerResult:
        """Список участников с кнопками для редактирования колоды (admin view)."""
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN)
        return self._tournament_status_result(tournament_id, tg_id=tg_id, page=page)

    def handle_admin_status_me(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает администратору страницу со своей строкой в статусе турнира."""
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN)
        participants = sort_participants(self.svc.list_participants_for_tournament(tournament_id))
        page = participant_page_for_tg_id(participants, tg_id)
        if page is None:
            return HandlerResult(NOT_REGISTERED_IN_TOURNAMENT, is_alert=True)
        return self._tournament_status_result(
            tournament_id,
            tg_id=tg_id,
            page=page,
            highlight_tg_id=tg_id,
        )

    def handle_endstep_identity_map(self, tg_id: int, tournament_id: int, page: int = 0) -> HandlerResult:
        """Show Endstep nick → Telegram nick for one Endstep tournament."""
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        if tournament is None:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN)
        if not is_konetskhod_club(tournament.club):
            return HandlerResult("Эта выгрузка доступна только для турниров Концехода.", is_alert=True)

        participants = self.svc.list_participants_for_tournament(tournament_id)
        participants.sort(
            key=lambda participant: (
                not bool((participant.user.endstep_username or "").strip()),
                (participant.user.endstep_username or "").strip().casefold(),
                participant.user.id,
            )
        )
        total = len(participants)
        pages = max(1, (total + ENDSTEP_IDENTITY_PAGE_SIZE - 1) // ENDSTEP_IDENTITY_PAGE_SIZE)
        page = min(max(page, 0), pages - 1)
        start = page * ENDSTEP_IDENTITY_PAGE_SIZE
        visible = participants[start : start + ENDSTEP_IDENTITY_PAGE_SIZE]

        lines = [
            "👤 Endstep — Telegram",
            f"Игроков: {total} · страница {page + 1}/{pages}",
            "",
        ]
        for participant in visible:
            user = participant.user
            endstep_name = (user.endstep_username or "").strip() or "—"
            telegram_name = f"@{user.username}" if user.username else "—"
            lines.append(f"{endstep_name} — {telegram_name}")
        if not visible:
            lines.append("В турнире пока нет игроков.")

        return HandlerResult(
            "\n".join(lines),
            keyboard=self.keyboards.endstep_identity_keyboard(tournament_id, page, pages),
        )

    def handle_admin_show_filled(self, tg_id: int, tournament_id: int, page: int = 0) -> HandlerResult:
        """Разворачивает скрытых заполненных участников или столы."""
        if not self._is_privileged_for_tournament(tg_id, tournament_id):
            return HandlerResult(NOT_ADMIN)
        return self._tournament_status_result(tournament_id, show_filled=True, tg_id=tg_id, page=page)

    def handle_reveal_decks(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Снимает скрытие колод — делает их видимыми для всех."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        try:
            self.svc.set_decks_hidden(tournament_id, hidden=False)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(tournament_id, prefix=DECKS_REVEALED, tg_id=tg_id)

    def handle_hide_decks(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Скрывает колоды участников."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        try:
            self.svc.set_decks_hidden(tournament_id, hidden=True)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(tournament_id, prefix="🙈 Колоды скрыты.", tg_id=tg_id)

    def _archetype_keyboard_for_participant(
        self,
        participant_id: int,
        player_tg_id: int | None,
        expanded: bool = False,
        caller_tg_id: int | None = None,
        tournament_id: int | None = None,
        page: int | None = None,
    ) -> HandlerResult:
        """Строит HandlerResult с клавиатурой архетипов для участника."""
        arch_list, has_more = build_archetype_menu(self.arch_svc, player_tg_id, expanded)
        caller = self.user_svc.get_by_tg_id(caller_tg_id) if caller_tg_id else None
        show_emoji = not (caller and caller.hide_deck_emoji)
        show_actions = bool(
            caller_tg_id
            and tournament_id is not None
            and self._is_privileged_for_tournament(caller_tg_id, tournament_id)
        )
        return HandlerResult(
            CHOOSE_ARCHETYPE,
            keyboard=self.keyboards.admin_archetype_select_keyboard(
                participant_id,
                arch_list,
                has_more,
                show_emoji,
                tournament_id=tournament_id,
                show_actions=show_actions,
                page=page,
            ),
        )

    def handle_pick_participant_arch(
        self, tg_id: int, participant_id: int, expanded: bool = False, page: int | None = None
    ) -> HandlerResult:
        """Показывает выбор архетипа для конкретного участника."""
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if (
            not self._is_privileged_for_tournament(tg_id, p.tournament_id)
            and not self._features.can_fill_opponent_decks()
        ):
            return HandlerResult(NOT_ADMIN)
        user = self.user_svc.get_by_id(p.user_id)
        player_tg_id = user.tg_id if user else None
        return self._archetype_keyboard_for_participant(
            participant_id,
            player_tg_id,
            expanded,
            caller_tg_id=tg_id,
            tournament_id=p.tournament_id,
            page=page,
        )

    def handle_pick_participant_arch_more(
        self, tg_id: int, participant_id: int, page: int | None = None
    ) -> HandlerResult:
        """Разворачивает полный список архетипов для участника (история + топ)."""
        return self.handle_pick_participant_arch(tg_id, participant_id, expanded=True, page=page)

    def handle_set_participant_arch(
        self, tg_id: int, participant_id: int, archetype_id: int, page: int | None = None
    ) -> HandlerResult:
        """Устанавливает архетип участнику, затем возвращает обновлённый статус турнира."""
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if (
            not self._is_privileged_for_tournament(tg_id, p.tournament_id)
            and not self._features.can_fill_opponent_decks()
        ):
            return HandlerResult(NOT_ADMIN)
        archetypes = {a.id: a.name for a in self.arch_svc.list_archetypes()}
        arch_name = archetypes.get(archetype_id, "?")
        target = self.user_svc.get_by_id(p.user_id)
        try:
            self.svc.set_participant_archetype(
                participant_id=participant_id,
                archetype_id=archetype_id,
                deck_added_by_tg_id=tg_id,
                ranked_activation_source=(
                    RANKED_ACTIVATION_SELF_BOT if target is not None and target.tg_id == tg_id else None
                ),
            )
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(
            p.tournament_id,
            prefix=ADMIN_ARCH_SAVED.format(archetype_name=arch_name),
            tg_id=tg_id,
            page=page or 0,
        )

    def handle_set_participant_custom_arch(
        self, tg_id: int, participant_id: int, arch_name: str, page: int | None = None
    ) -> HandlerResult:
        """Создаёт архетип по введённому названию и присваивает участнику."""
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        if (
            not self._is_privileged_for_tournament(tg_id, p.tournament_id)
            and not self._features.can_fill_opponent_decks()
        ):
            return HandlerResult(NOT_ADMIN)
        target = self.user_svc.get_by_id(p.user_id)
        try:
            arch = self.arch_svc.get_or_create_by_name(arch_name, is_custom=True)
            self.svc.set_participant_archetype(
                participant_id=participant_id,
                archetype_id=arch.id,
                deck_added_by_tg_id=tg_id,
                ranked_activation_source=(
                    RANKED_ACTIVATION_SELF_BOT if target is not None and target.tg_id == tg_id else None
                ),
            )
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(
            p.tournament_id,
            prefix=ADMIN_ARCH_SAVED.format(archetype_name=arch.name),
            tg_id=tg_id,
            page=page or 0,
        )

    def handle_player_actions(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Меню действий с игроком (⋯); права отдельных кнопок задаёт клавиатура."""
        is_admin = self.user_svc.is_admin(tg_id)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        user = self.user_svc.get_by_id(p.user_id)
        has_pairings = AetherhubImportService(self.svc.db).has_pairings(tournament_id)
        tournament = get_tournament(self.svc.db, tournament_id)
        is_privileged = self.user_svc.is_privileged_for_tournament(tg_id, tournament)
        is_target_scorekeeper = bool(user.is_scorekeeper) if user else False
        is_target_poll_organizer = bool(user.is_poll_organizer) if user else False
        name = (
            format_participant_name(user.first_name if user else None, user.last_name if user else None) or f"id{p.id}"
        )
        username_str = f"\n@{user.username}" if user and user.username else ""
        text = f"Игрок: {name}{username_str}"
        if is_privileged:
            arch_name = p.archetype.name if p.archetype else "колода не указана"
            text += f"\nКолода: {arch_name}"
        return HandlerResult(
            text,
            keyboard=self.keyboards.admin_player_actions_keyboard(
                participant_id,
                tournament_id,
                is_admin=is_admin,
                has_pairings=has_pairings,
                is_target_scorekeeper=is_target_scorekeeper,
                is_target_poll_organizer=is_target_poll_organizer,
                is_privileged=is_privileged,
                page=page,
                swiss_ongoing=(
                    tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
                    and tournament.status == models.TournamentStatus.ONGOING
                ),
            ),
        )

    def handle_toggle_scorekeeper(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Назначить или снять роль скорипера у игрока."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        target_user = self.user_svc.get_by_id(p.user_id)
        if target_user is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        name = format_participant_name(target_user.first_name, target_user.last_name) or f"id{p.id}"
        new_value = self.user_svc.toggle_scorekeeper(target_user.tg_id)
        msg = SCOREKEEPER_GRANTED.format(name=name) if new_value else SCOREKEEPER_REVOKED.format(name=name)
        result = self._tournament_status_result(tournament_id, prefix=msg, tg_id=tg_id, page=page or 0)
        result.answer_text = msg
        return result

    def handle_toggle_poll_organizer(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Назначить или снять роль организатора голосований у игрока (только админ)."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        target_user = self.user_svc.get_by_id(p.user_id)
        if target_user is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        name = format_participant_name(target_user.first_name, target_user.last_name) or f"id{p.id}"
        new_value = self.user_svc.toggle_poll_organizer(target_user.tg_id)
        msg = POLL_ORGANIZER_GRANTED.format(name=name) if new_value else POLL_ORGANIZER_REVOKED.format(name=name)
        result = self._tournament_status_result(tournament_id, prefix=msg, tg_id=tg_id, page=page or 0)
        result.answer_text = msg
        return result

    def handle_player_opponents(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Список оппонентов игрока из AetherHub-пейрингов."""
        if not self._is_privileged_for_tournament(tg_id, tournament_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        user = self.user_svc.get_by_id(p.user_id)
        player_name = (
            format_participant_name(user.first_name if user else None, user.last_name if user else None) or f"id{p.id}"
        )
        opponents, err = AetherhubImportService(self.svc.db).get_player_opponents(tournament_id, participant_id)
        _errors = {
            "no_pairings": "Пейринги не импортированы для этого турнира.",
            "not_in_pairings": "Игрок не найден в пейрингах.",
            "not_found": PARTICIPANT_NOT_FOUND,
        }
        if err:
            return HandlerResult(_errors.get(err, err), is_alert=True)
        lines = [f"Оппоненты {player_name}:\n"]
        for opp in opponents:
            if opp.opponent_name is None:
                lines.append(f"Раунд {opp.round_number}: bye")
            else:
                opp_user = opp.opponent_user
                opp_display = (
                    format_participant_name(
                        opp_user.first_name if opp_user else None,
                        opp_user.last_name if opp_user else None,
                    )
                    or opp.opponent_name
                )
                username_part = f" (@{opp_user.username})" if opp_user and opp_user.username else ""
                opp_part = opp.opponent_participant
                deck_part = opp_part.archetype.name if opp_part and opp_part.archetype else "колода не указана"
                lines.append(f"Раунд {opp.round_number}: {opp_display}{username_part} — {deck_part}")
        return HandlerResult(
            "\n".join(lines),
            keyboard=self.keyboards.admin_opponents_keyboard(participant_id, tournament_id, page=page),
        )

    def handle_remove_participant_confirm(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Запрос подтверждения перед удалением участника."""
        if not self._is_privileged_for_tournament(tg_id, tournament_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None or p.tournament_id != tournament_id:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        user = self.user_svc.get_by_id(p.user_id)
        name = (
            format_participant_name(user.first_name if user else None, user.last_name if user else None) or f"id{p.id}"
        )
        username_str = f" (@{user.username})" if user and user.username else ""
        tournament = get_tournament(self.svc.db, tournament_id)
        is_swiss = (
            tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
            and tournament.status == models.TournamentStatus.ONGOING
        )
        return HandlerResult(
            f"{'Дропнуть' if is_swiss else 'Удалить'} {name}{username_str} из турнира?",
            keyboard=self.keyboards.admin_remove_confirm_keyboard(participant_id, tournament_id, page=page),
        )

    def handle_remove_participant(
        self, tg_id: int, participant_id: int, tournament_id: int, page: int | None = None
    ) -> HandlerResult:
        """Удаляет участника из турнира и возвращает обновлённый статус."""
        if not self._is_privileged_for_tournament(tg_id, tournament_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None or p.tournament_id != tournament_id:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        user = self.user_svc.get_by_id(p.user_id)
        name = (
            format_participant_name(user.first_name if user else None, user.last_name if user else None) or f"id{p.id}"
        )
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
            if (
                tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS
                and tournament.status == models.TournamentStatus.ONGOING
            ):
                self.svc.drop_participant(tournament_id, p.user_id)
                return self._tournament_status_result(
                    tournament_id, prefix=f"🗑 {name} дропнут.", tg_id=tg_id, page=page or 0
                )
            self.svc.unregister_participant(tournament_id, p.user_id)
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(
            tournament_id, prefix=f"🗑 {name} удалён из турнира.", tg_id=tg_id, page=page or 0
        )

    def handle_fill_opponents(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает незаполненных оппонентов пользователя из AetherHub-пейрингов."""
        if not self._features.can_fill_opponent_decks():
            return HandlerResult(NOT_ADMIN, is_alert=True)

        user = self.user_svc.get_by_tg_id(tg_id)
        if not user:
            return HandlerResult("Профиль не найден.", is_alert=True)

        participants = self.svc.list_participants_for_tournament(tournament_id)
        opponents, err = AetherhubImportService(self.svc.db).get_unfilled_opponents(
            tournament_id, user.id, participants
        )

        _errors = {
            "no_pairings": "Пейринги AetherHub не импортированы для этого турнира.",
            "not_in_pairings": "Ваше имя не найдено в пейрингах AetherHub.",
            "all_filled": "Все оппоненты уже заполнены.",
        }
        if err:
            return HandlerResult(_errors.get(err, err), is_alert=True)

        return HandlerResult(
            "Выберите оппонента для записи колоды (по раундам):",
            keyboard=self.keyboards.opponents_keyboard(opponents),
        )

    def handle_archive(self, tg_id: int) -> HandlerResult:
        """Последние 20 закрытых турниров — список кнопок как в /tournaments."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        tournaments = self.svc.list_closed_tournaments()
        if not tournaments:
            return HandlerResult("Архив пуст — закрытых турниров нет.")
        tour_list = [(t.id, t.title) for t in tournaments]
        return HandlerResult("📁 Архив турниров:", keyboard=self.keyboards.tournament_list_keyboard(tour_list))

    def handle_tournament_status(self, tg_id: int) -> HandlerResult:
        if not self.user_svc.is_privileged(tg_id):
            return HandlerResult(NOT_ADMIN)
        tournaments = self.svc.list_all_active_tournaments()
        if not self.user_svc.is_admin(tg_id):
            tournaments = [
                tournament
                for tournament in tournaments
                if self.user_svc.is_privileged_for_tournament(tg_id, tournament)
            ]
        if not tournaments:
            return HandlerResult(NO_ACTIVE_TOURNAMENT)
        blocks = []
        for t in tournaments:
            participants = sort_participants(self.svc.list_participants_for_tournament(t.id))
            total = len(participants)
            with_deck = sum(1 for p in participants if p.archetype)
            for page in range(page_count(total)):
                start, end = page_bounds(page, total)
                blocks.append(
                    format_tournament_status(
                        t.title,
                        t.status.label_ru,
                        participants[start:end],
                        total=total,
                        with_deck=with_deck,
                        page=page,
                    )
                )
        return HandlerResult("\n\n---\n\n".join(blocks))

    def handle_schedule(self, tg_id: int, schedule_text: str) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        return HandlerResult(schedule_text)

    def handle_close_tournament(self, tg_id: int) -> HandlerResult:
        if not self.user_svc.is_privileged(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        if not self.user_svc.is_privileged_for_tournament(tg_id, active):
            return HandlerResult(NOT_ADMIN)
        return self.handle_close_tournament_by_id(tg_id, active.id)

    def handle_close_tournament_by_id(
        self,
        tg_id: int,
        tournament_id: int,
        confirmed: bool = False,
    ) -> HandlerResult:
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if tournament.status == models.TournamentStatus.CLOSED:
            return HandlerResult("⚠️ Турнир уже закрыт.", is_alert=True)

        if tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS:
            if not confirmed:
                return RoundResultsHandler(self.svc.db, self.keyboards).handle_swiss_finish_prompt(tournament_id, tg_id)
            try:
                InternalSwissService(self.svc.db).finish(tournament_id, tg_id)
            except (ValueError, RoundResultError) as exc:
                if settings.DEBUG and tournament.chat_id in settings.chat_ids:
                    # Debug escape hatch: an unfinished Swiss cannot be closed normally,
                    # which blocks resetting a simulator tournament. Prod keeps the error.
                    return HandlerResult(
                        f"{exc}\n\n🧹 Debug-бот может закрыть турнир принудительно — места не расставляются.",
                        keyboard=self.keyboards.debug_swiss_force_close_keyboard(tournament_id),
                    )
                return HandlerResult(str(exc), is_alert=True)
            return HandlerResult(TOURNAMENT_CLOSED_MSG, tournament_id=tournament_id)

        participants = self.svc.list_participants_for_tournament(tournament_id)
        if participants and not confirmed:
            return HandlerResult(
                f"⚠️ В турнире «{tournament.title}» записано игроков: {len(participants)}.\nЗакрыть турнир?",
                keyboard=self.keyboards.close_tournament_confirm_keyboard(tournament_id),
                tournament_id=tournament_id,
            )

        try:
            self.svc.close_tournament(tournament_id, closed_by_tg_id=tg_id)
        except errors.TournamentInvalidState:
            return HandlerResult("⚠️ Турнир уже закрыт.", is_alert=True)
        return HandlerResult(TOURNAMENT_CLOSED_MSG, tournament_id=tournament_id)

    def handle_reopen_tournament(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Кнопка «🔓 Сделать активным» — возвращает закрытый турнир в регистрацию."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        tournament = self.svc.db.get(models.Tournament, tournament_id)
        if tournament is not None and tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS:
            return HandlerResult("Завершённый Swiss-турнир нельзя вернуть в регистрацию.", is_alert=True)
        try:
            t = self.svc.reopen_tournament(tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        except errors.TournamentInvalidState:
            return HandlerResult("⚠️ Турнир и так активен.", is_alert=True)
        except errors.TournamentAlreadyExists:
            return HandlerResult(
                "⚠️ В этом чате уже открыты два турнира — сначала закройте один.",
                is_alert=True,
            )
        return HandlerResult(f"🔓 Турнир «{t.title}» снова активен (регистрация открыта).")

    def handle_create_tournament(
        self,
        tg_id: int,
        chat_id: int,
        title: str | None = None,
        *,
        club: str | None = None,
        is_online: bool = False,
        is_draft: bool = False,
        title_prefix: str = "",
    ) -> HandlerResult:
        """Создать новый турнир в текущем чате."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not title:
            if is_konetskhod_club(club):
                title = konetskhod_title(self.svc.db, title_prefix)
            else:
                club_label = f"{club} " if club else ""
                format_label = "" if is_draft else "Pauper "
                title = f"{title_prefix}{club_label}{format_label}{datetime.now().strftime('%d.%m.%Y')}"
        elif title_prefix and not title.startswith(title_prefix):
            title = f"{title_prefix}{title}"
        try:
            t = self.svc.create_tournament(
                TournamentCreate(
                    title=title,
                    chat_id=chat_id,
                    club=club,
                    is_online=is_online,
                    is_draft=is_draft,
                    engine_mode=(
                        models.TournamentEngineMode.INTERNAL_SWISS
                        if is_draft or club == "Endstep-ru"
                        else models.TournamentEngineMode.AETHERHUB
                    ),
                    created_by_tg_id=tg_id,
                    decklist_reminders_enabled=not is_draft,
                )
            )
        except errors.TournamentAlreadyExists:
            return HandlerResult(TOURNAMENT_ALREADY_EXISTS_MSG, is_alert=True)
        return HandlerResult(f"✅ Турнир создан: «{t.title}»", tournament_id=t.id)

    def handle_delete_tournament(self, tg_id: int) -> HandlerResult:
        """Удалить активный турнир вместе с участниками (для дебага, через /delete_tournament)."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        title = active.title
        self.svc.delete_tournament(active.id)
        return HandlerResult(f"🗑 Турнир «{title}» удалён.")

    def handle_export_players(self, tg_id: int, tournament_id: int) -> str | None:
        """Возвращает plain-text список «Имя Фамилия» или None если нет прав."""
        try:
            tournament = self.svc.db.get(models.Tournament, tournament_id)
            if not self.user_svc.is_admin(tg_id) and (
                tournament is None or not self.user_svc.is_privileged_for_tournament(tg_id, tournament)
            ):
                return None
            return ExportService(self.svc.db).export_players_list(tournament_id)
        except errors.TournamentNotFound:
            return None

    def handle_export_swiss_players(self, tg_id: int, tournament_id: int) -> str | None:
        """Возвращает Swiss-список с Telegram-никами, очками и городами."""
        result = self.handle_export_swiss_players_page(tg_id, tournament_id)
        return result[0] if result is not None else None

    def handle_export_swiss_players_page(self, tg_id: int, tournament_id: int, page: int = 0) -> tuple[str, int] | None:
        """Возвращает одну страницу Swiss-списка и общее число страниц."""
        try:
            tournament = self.svc.db.get(models.Tournament, tournament_id)
            if not self.user_svc.is_admin(tg_id) and (
                tournament is None or not self.user_svc.is_privileged_for_tournament(tg_id, tournament)
            ):
                return None
            return ExportService(self.svc.db).export_swiss_players_with_points_page(tournament_id, page=page)
        except errors.TournamentNotFound:
            return None

    def handle_export_excel(self, tg_id: int, tournament_id: int) -> list[tuple[bytes, str]] | None:
        """Файлы Excel-выгрузки: участники + паринги (если известны). None если нет прав."""
        try:
            tournament = self.svc.db.get(models.Tournament, tournament_id)
            if not self.user_svc.is_admin(tg_id) and (
                tournament is None or not self.user_svc.is_privileged_for_tournament(tg_id, tournament)
            ):
                return None
            export = ExportService(self.svc.db)
            files = [export.export_participants_excel(tournament_id)]
            pairings = export.export_pairings_excel(tournament_id)
            if pairings is not None:
                files.append(pairings)
            return files
        except errors.TournamentNotFound:
            return None

    def can_build_meta_chart(self, tg_id: int, tournament_id: int) -> bool:
        """Можно ли строить «Метагейм-срез»: есть права и турнир существует.

        График работает и по ходу турнира, поэтому завершённость не требуется. Саму
        картинку собирает `bot.chart` — рисование уходит в поток, и держать эту механику
        в чистом хендлере незачем.
        """
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return False
        return self.user_svc.is_privileged_for_tournament(tg_id, tournament)

    def standings_availability(self, tg_id: int, tournament_id: int) -> str:
        """Доступность «Итоговых стендингов»: 'no_access' | 'not_ready' | 'ok'.

        Стендинги — итоговые, поэтому показываем только для завершённого турнира (у всех
        матчей есть счёт), иначе картинка «Итоговые» врала бы промежуточными результатами.
        Дополнительно, для AetherHub-турниров, — не раньше минимальной длительности с начала
        игры: у AetherHub счёт раннего раунда может появиться раньше, чем сыграны следующие,
        и `is_tournament_complete` в этот зазор преждевременно True. Турниры без ``started_at``
        (например, из meta-import) этот гард не затрагивает.
        """
        if not self.can_build_meta_chart(tg_id, tournament_id):
            return "no_access"
        tournament = get_tournament(self.svc.db, tournament_id)
        if (
            tournament.engine_mode != models.TournamentEngineMode.INTERNAL_SWISS
            and tournament.started_at is not None
            and models.utc_now() - tournament.started_at < MIN_TOURNAMENT_DURATION
        ):
            return "not_ready"
        if not AetherhubImportService(self.svc.db).is_tournament_complete(tournament_id):
            return "not_ready"
        return "ok"

    def handle_delete_tournament_prompt(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает запрос подтверждения удаления турнира."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        n = len(self.svc.list_participants_for_tournament(tournament_id))
        text = f"⚠️ Удалить турнир «{t.title}»?\nБудет удалено {n} участник(ов). Действие необратимо."
        return HandlerResult(text, keyboard=self.keyboards.delete_tournament_confirm_keyboard(tournament_id))

    def handle_create_poll(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Проверяет возможность создания опроса, возвращает HandlerResult("ok") или ошибку.
        Реальная отправка опроса выполняется Telegram-обёрткой после этого вызова.
        """
        if not self.user_svc.can_manage_polls(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if PollService(self.svc.db).get_poll_for_tournament(tournament_id):
            return HandlerResult("⚠️ Для этого турнира уже есть опрос.", is_alert=True)
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return HandlerResult(t.title)

    def handle_delete_tournament_confirm(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Выполняет удаление после подтверждения."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        title = t.title
        self.svc.delete_tournament(tournament_id)
        return HandlerResult(f"🗑 Турнир «{title}» удалён.")

    # ── Личная рассылка владельца участникам турнира ────────────────────────────

    def _broadcast_guard(self, tg_id: int, tournament_id: int) -> HandlerResult | None:
        """Только владелец бота и только для существующего турнира."""
        if settings.OWNER_CHAT_ID is None or tg_id != settings.OWNER_CHAT_ID:
            return HandlerResult(BROADCAST_OWNER_ONLY, is_alert=True)
        try:
            get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return None

    def handle_broadcast_start(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Кнопка «📩 Написать участникам» — бот ждёт текст сообщения."""
        guard = self._broadcast_guard(tg_id, tournament_id)
        if guard is not None:
            return guard
        return HandlerResult(
            BROADCAST_PROMPT.format(limit=BROADCAST_MAX_LENGTH),
            keyboard=broadcast_input_keyboard(tournament_id),
            tournament_id=tournament_id,
        )

    def handle_broadcast_preview(self, tg_id: int, tournament_id: int, text: str) -> HandlerResult:
        """Введённый текст — показываем ещё раз и спрашиваем подтверждение, с кем отправка."""
        guard = self._broadcast_guard(tg_id, tournament_id)
        if guard is not None:
            return guard
        text = text.strip()
        if len(text) > BROADCAST_MAX_LENGTH:
            return HandlerResult(
                BROADCAST_TOO_LONG.format(length=len(text), limit=BROADCAST_MAX_LENGTH),
                is_alert=True,
            )
        recipients = self.svc.list_broadcast_recipients(tournament_id)
        if not recipients:
            return HandlerResult(BROADCAST_NO_RECIPIENTS, is_alert=True)
        return HandlerResult(
            format_broadcast_preview(text, recipients),
            keyboard=broadcast_confirm_keyboard(tournament_id),
            tournament_id=tournament_id,
        )

    def handle_broadcast_send(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Подтверждение — отдать обёртке список тех, кому реально отправлять."""
        guard = self._broadcast_guard(tg_id, tournament_id)
        if guard is not None:
            return guard
        recipients = self.svc.list_broadcast_recipients(tournament_id)
        if not recipients:
            return HandlerResult(BROADCAST_NO_RECIPIENTS, is_alert=True)
        return HandlerResult(
            f"Отправляю {len(recipients)} участникам…",
            tournament_id=tournament_id,
            broadcast_recipients=recipients,
        )

    def handle_meta_import_start(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает инструкцию — бот ждёт текст таблицы."""
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        return HandlerResult(META_IMPORT_PROMPT, tournament_id=tournament_id)

    def handle_meta_import_table(self, tg_id: int, tournament_id: int, text: str) -> HandlerResult:
        """Парсит и импортирует таблицу мета-данных."""
        try:
            tournament = get_tournament(self.svc.db, tournament_id)
            if not self.user_svc.is_privileged_for_tournament(tg_id, tournament):
                return HandlerResult(NOT_ADMIN, is_alert=True)
            result = MetaTableImportService(self.svc.db).import_from_table(tournament_id, text, added_by_tg_id=tg_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        summary = result.summary()
        status_result = self._tournament_status_result(tournament_id, prefix=summary, tg_id=tg_id)
        return status_result
