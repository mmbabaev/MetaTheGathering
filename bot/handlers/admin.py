# Админ-панель — чистая бизнес-логика

import re
from datetime import datetime

from bot.features import FeatureService
from bot.handlers.base import HandlerResult
from bot.handlers.player import build_archetype_menu
from bot.keyboards import Keyboards
from bot.messages import (
    ADMIN_ARCH_SAVED,
    BULK_ADD_EMPTY,
    CHOOSE_ARCHETYPE,
    DECKS_REVEALED,
    MULTIPLE_TOURNAMENTS_MSG,
    NO_ACTIVE_TOURNAMENT,
    NO_DECK_NAME,
    NOT_ADMIN,
    PARTICIPANT_NOT_FOUND,
    PLAYER_ADDED,
    REGISTRATION_CLOSED,
    TOURNAMENT_ALREADY_EXISTS_MSG,
    TOURNAMENT_CLOSED_MSG,
    TOURNAMENT_NOT_FOUND,
    format_tournament_status,
    sort_participants,
)
from core.schemas import TournamentCreate
from services import errors
from services.aetherhub_import_service import AetherhubImportService
from services.archetype import ArchetypeService
from services.export import ExportService
from services.poll import PollService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament


def parse_add_player_command(message_text: str, bot_username: str | None) -> tuple[str, str] | None:
    """
    Разбор текста /add_player … в (username_игрока, название_колоды).

    Поддерживает случай, когда пользователь пишет /add_player@nickname Колода
    и Telegram воспринимает @nickname как суффикс команды, а не как игрока:
    тогда nickname — это игрок, остаток строки — колода.

    Все пробельные символы Unicode приводятся к обычному пробелу: после выбора
    @username клиенты иногда вставляют узкий неразрывный пробел (U+202F) и т.п.,
    из‑за чего str.split() не отделяет ник от названия колоды.
    """
    if not message_text or not message_text.strip():
        return None
    text = re.sub(r"\s+", " ", message_text.strip())
    parts = text.split(None, 1)
    if not parts:
        return None
    cmd_token = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not cmd_token.lower().startswith("/add_player"):
        return None

    suffix = ""
    if "@" in cmd_token:
        _, _, suffix = cmd_token.partition("@")

    bot_u = (bot_username or "").lower().lstrip("@")
    if suffix and suffix.lower() != bot_u:
        if not rest:
            return None
        return (suffix, rest)

    if not rest:
        return None
    user_and_deck = rest.split(None, 1)
    if len(user_and_deck) < 2:
        return None
    username = user_and_deck[0].lstrip("@")
    deck_name = user_and_deck[1].strip()
    if not username or not deck_name:
        return None
    return (username, deck_name)


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

    def handle_add_me(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        deck_name: str,
    ) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not deck_name:
            return HandlerResult(NO_DECK_NAME)
        active, err = self._resolve_tournament()
        if err:
            return err
        try:
            db_user = self.user_svc.get_or_create(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            archetype = self.arch_svc.get_or_create_by_name(deck_name)
            self.svc.register_participant(
                tournament_id=active.id,
                user_id=db_user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
            )
            user_label = f"@{username}" if username else (first_name or f"id{tg_id}")
            return HandlerResult(
                PLAYER_ADDED.format(
                    user=user_label,
                    archetype_name=archetype.name,
                )
            )
        except errors.ParticipantAlreadyRegistered:
            return HandlerResult("Вы уже записаны на этот турнир.")
        except errors.TournamentInvalidState:
            return HandlerResult("Регистрация на этот турнир закрыта.")

    def handle_add_player(
        self,
        tg_id: int,
        *,
        target_tg_id: int,
        target_username: str | None,
        deck_name: str,
        target_first_name: str | None = None,
        target_last_name: str | None = None,
    ) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        try:
            target_user = self.user_svc.get_or_create(
                tg_id=target_tg_id,
                username=target_username,
                first_name=target_first_name,
                last_name=target_last_name,
            )
            archetype = self.arch_svc.get_or_create_by_name(deck_name)
            self.svc.register_participant(
                tournament_id=active.id,
                user_id=target_user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
            )
            user_label = _player_display_label(target_username, target_first_name, target_tg_id)
            return HandlerResult(
                PLAYER_ADDED.format(
                    user=user_label,
                    archetype_name=archetype.name,
                )
            )
        except errors.ParticipantAlreadyRegistered:
            user_label = _player_display_label(target_username, target_first_name, target_tg_id)
            return HandlerResult(f"{user_label} уже записан на этот турнир.")
        except errors.TournamentInvalidState:
            return HandlerResult("Регистрация на этот турнир закрыта.")

    def handle_add_players(
        self,
        tg_id: int,
        entries: list[tuple[int, str | None, str | None, str]],
    ) -> HandlerResult:
        """entries: (target_tg_id, username, first_name, deck_name) — после резолва в Telegram."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not entries:
            return HandlerResult("Нет данных для обработки.")
        active, err = self._resolve_tournament()
        if err:
            return err
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
        if not self.user_svc.is_admin(tg_id):
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
        return self._tournament_status_result(tournament_id, prefix="\n".join(lines))

    def _tournament_status_result(
        self, tournament_id: int, prefix: str = "", show_filled: bool = False
    ) -> HandlerResult:
        """Строит HandlerResult со статусом турнира и клавиатурой участников.

        prefix — необязательный текст (например, итог операции), который добавляется
        перед статусом через пустую строку.
        show_filled — показывать кнопки заполненных участников.
        """
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        participants = sort_participants(self.svc.list_participants_for_tournament(tournament_id))
        status_text = format_tournament_status(t.title, t.status.label_ru, participants, decks_hidden=t.decks_hidden)
        text = f"{prefix}\n\n{status_text}" if prefix else status_text
        return HandlerResult(
            text,
            keyboard=self.keyboards.admin_participants_keyboard(
                participants, tournament_id=tournament_id, show_filled=show_filled
            ),
        )

    def handle_admin_status(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Список участников с кнопками для редактирования колоды (admin view)."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        return self._tournament_status_result(tournament_id)

    def handle_admin_show_filled(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает кнопки заполненных участников (разворачивает скрытый список)."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        return self._tournament_status_result(tournament_id, show_filled=True)

    def handle_reveal_decks(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Снимает скрытие колод — делает их видимыми для всех."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        try:
            self.svc.set_decks_hidden(tournament_id, hidden=False)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(tournament_id, prefix=DECKS_REVEALED)

    def _archetype_keyboard_for_participant(
        self, participant_id: int, player_tg_id: int | None, expanded: bool = False
    ) -> HandlerResult:
        """Строит HandlerResult с клавиатурой архетипов для участника."""
        arch_list, has_more = build_archetype_menu(self.arch_svc, player_tg_id, expanded)
        return HandlerResult(
            CHOOSE_ARCHETYPE,
            keyboard=self.keyboards.admin_archetype_select_keyboard(participant_id, arch_list, has_more),
        )

    def handle_admin_pick_arch(self, tg_id: int, participant_id: int, expanded: bool = False) -> HandlerResult:
        """Показывает выбор архетипа для конкретного участника."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        user = self.user_svc.get_by_id(p.user_id)
        player_tg_id = user.tg_id if user else None
        return self._archetype_keyboard_for_participant(participant_id, player_tg_id, expanded)

    def handle_admin_arch_more(self, tg_id: int, participant_id: int) -> HandlerResult:
        """Разворачивает полный список архетипов для участника (история + топ)."""
        return self.handle_admin_pick_arch(tg_id, participant_id, expanded=True)

    def handle_admin_set_arch(self, tg_id: int, participant_id: int, archetype_id: int) -> HandlerResult:
        """Устанавливает архетип участнику, затем возвращает обновлённый статус турнира."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        archetypes = {a.id: a.name for a in self.arch_svc.list_archetypes()}
        arch_name = archetypes.get(archetype_id, "?")
        try:
            self.svc.set_participant_archetype(participant_id=participant_id, archetype_id=archetype_id)
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(p.tournament_id, prefix=ADMIN_ARCH_SAVED.format(archetype_name=arch_name))

    def handle_admin_custom_arch_text(self, tg_id: int, participant_id: int, arch_name: str) -> HandlerResult:
        """Создаёт архетип по введённому названию и присваивает участнику."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            arch = self.arch_svc.get_or_create_by_name(arch_name, is_custom=True)
            self.svc.set_participant_archetype(participant_id=participant_id, archetype_id=arch.id)
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return HandlerResult(ADMIN_ARCH_SAVED.format(archetype_name=arch.name))

    def handle_admin_opponents(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Показывает незаполненных оппонентов пользователя из AetherHub-пейрингов."""
        if not self.user_svc.is_admin(tg_id) and not self._features.opponents_for_all():
            return HandlerResult(NOT_ADMIN, is_alert=True)

        user = self.user_svc.get_by_tg_id(tg_id)
        if not user:
            return HandlerResult("Профиль не найден.", is_alert=True)

        participants = self.svc.list_participants_for_tournament(tournament_id)
        opponent_participants, err = AetherhubImportService(self.svc.db).get_unfilled_opponents(
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
            "Выберите оппонента для записи колоды:",
            keyboard=self.keyboards.admin_participants_keyboard(opponent_participants),
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
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        tournaments = self.svc.list_all_active_tournaments()
        if not tournaments:
            return HandlerResult(NO_ACTIVE_TOURNAMENT)
        blocks = [
            format_tournament_status(
                t.title, t.status.label_ru, sort_participants(self.svc.list_participants_for_tournament(t.id))
            )
            for t in tournaments
        ]
        return HandlerResult("\n\n---\n\n".join(blocks))

    def handle_schedule(self, tg_id: int, schedule_text: str) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        return HandlerResult(schedule_text)

    def handle_close_tournament(self, tg_id: int) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        self.svc.close_tournament(active.id)
        return HandlerResult(TOURNAMENT_CLOSED_MSG)

    def handle_close_tournament_by_id(self, tg_id: int, tournament_id: int, allow_empty: bool = False) -> HandlerResult:
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN, is_alert=True)
        if not allow_empty:
            participants = self.svc.list_participants_for_tournament(tournament_id)
            if not participants:
                return HandlerResult("⚠️ Нельзя закрыть пустой турнир — сначала добавьте участников.", is_alert=True)
        try:
            self.svc.close_tournament(tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        return HandlerResult(TOURNAMENT_CLOSED_MSG)

    def handle_create_tournament(self, tg_id: int, chat_id: int, title: str | None = None) -> HandlerResult:
        """Создать новый турнир в текущем чате."""
        if not self.user_svc.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not title:
            title = f"Pauper {datetime.now().strftime('%d.%m.%Y')}"
        try:
            t = self.svc.create_tournament(TournamentCreate(title=title, chat_id=chat_id))
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

    def handle_export_excel(self, tg_id: int, tournament_id: int) -> tuple[bytes, str] | None:
        """Возвращает (bytes, filename) или None если нет прав."""
        if not self.user_svc.is_admin(tg_id):
            return None
        try:
            return ExportService(self.svc.db).export_participants_excel(tournament_id)
        except errors.TournamentNotFound:
            return None

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
        if not self.user_svc.is_admin(tg_id):
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
