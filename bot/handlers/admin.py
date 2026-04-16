# Админ-панель — чистая бизнес-логика

import re

from core.config import settings
from services.tournament import TournamentService
from services.user import UserService
from services import errors
from bot.handlers.base import HandlerResult
from bot.handlers.player import build_archetype_menu
from bot.keyboards import (
    admin_participants_keyboard,
    admin_archetype_select_keyboard,
    delete_tournament_confirm_keyboard,
)
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
    MULTIPLE_TOURNAMENTS_MSG,
    PLAYER_ADDED,
    TOURNAMENT_CLOSED_MSG,
    TOURNAMENT_NOT_FOUND,
    REGISTRATION_CLOSED,
    BULK_ADD_EMPTY,
    PARTICIPANT_NOT_FOUND,
    ADMIN_ARCH_SAVED,
    CHOOSE_ARCHETYPE,
    format_tournament_status,
)


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
    def __init__(self, svc: TournamentService, user_svc: UserService) -> None:
        self.svc = svc
        self.user_svc = user_svc

    def _is_admin(self, tg_id: int) -> bool:
        from core.pretend import is_pretending
        if is_pretending(tg_id):
            return False
        if tg_id in settings.admin_ids:
            return True
        user = self.user_svc.get_by_tg_id(tg_id)
        return user is not None and (user.is_admin or user.is_superadmin)

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
        if not self._is_admin(tg_id):
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
            archetype = self.svc.get_or_create_archetype_by_name(deck_name)
            self.svc.register_participant(
                tournament_id=active.id,
                user_id=db_user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
            )
            user_label = f"@{username}" if username else (first_name or f"id{tg_id}")
            return HandlerResult(PLAYER_ADDED.format(
                user=user_label,
                archetype_name=archetype.name,
            ))
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
        if not self._is_admin(tg_id):
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
            archetype = self.svc.get_or_create_archetype_by_name(deck_name)
            self.svc.register_participant(
                tournament_id=active.id,
                user_id=target_user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
            )
            user_label = _player_display_label(target_username, target_first_name, target_tg_id)
            return HandlerResult(PLAYER_ADDED.format(
                user=user_label,
                archetype_name=archetype.name,
            ))
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
        if not self._is_admin(tg_id):
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
                archetype = self.svc.get_or_create_archetype_by_name(deck_name)
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
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)

        parsed: list[tuple[str, str | None]] = []
        for raw in names:
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split(None, 1)
            parsed.append((parts[0], parts[1] if len(parts) > 1 else None))

        if not parsed:
            return HandlerResult(BULK_ADD_EMPTY)

        entries: list[tuple[int, str]] = []
        for first_name, last_name in parsed:
            user, _ = self.user_svc.get_or_create_by_name(first_name, last_name)
            display = f"{first_name} {last_name}" if last_name else first_name
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
        self, tournament_id: int, prefix: str = ""
    ) -> HandlerResult:
        """Строит HandlerResult со статусом турнира и клавиатурой участников.

        prefix — необязательный текст (например, итог операции), который добавляется
        перед статусом через пустую строку.
        """
        from services.utils import get_tournament
        try:
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        participants = self.svc.list_participants_for_tournament(tournament_id)
        status_text = format_tournament_status(t.title, t.status.label_ru, participants)
        text = f"{prefix}\n\n{status_text}" if prefix else status_text
        return HandlerResult(text, keyboard=admin_participants_keyboard(participants))

    def handle_admin_status(self, tg_id: int, tournament_id: int) -> HandlerResult:
        """Список участников с кнопками для редактирования колоды (admin view)."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        return self._tournament_status_result(tournament_id)

    def _archetype_keyboard_for_participant(
        self, participant_id: int, player_tg_id: int | None, expanded: bool = False
    ) -> HandlerResult:
        """Строит HandlerResult с клавиатурой архетипов для участника."""
        arch_list, has_more = build_archetype_menu(self.svc, player_tg_id, expanded)
        return HandlerResult(
            CHOOSE_ARCHETYPE,
            keyboard=admin_archetype_select_keyboard(participant_id, arch_list, has_more),
        )

    def handle_admin_pick_arch(
        self, tg_id: int, participant_id: int, expanded: bool = False
    ) -> HandlerResult:
        """Показывает выбор архетипа для конкретного участника."""
        if not self._is_admin(tg_id):
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

    def handle_admin_set_arch(
        self, tg_id: int, participant_id: int, archetype_id: int
    ) -> HandlerResult:
        """Устанавливает архетип участнику, затем возвращает обновлённый статус турнира."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        p = self.svc.get_participant_by_id(participant_id)
        if p is None:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        archetypes = {a.id: a.name for a in self.svc.list_archetypes()}
        arch_name = archetypes.get(archetype_id, "?")
        try:
            self.svc.set_participant_archetype(participant_id=participant_id, archetype_id=archetype_id)
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return self._tournament_status_result(
            p.tournament_id, prefix=ADMIN_ARCH_SAVED.format(archetype_name=arch_name)
        )

    def handle_admin_custom_arch_text(
        self, tg_id: int, participant_id: int, arch_name: str
    ) -> HandlerResult:
        """Создаёт архетип по введённому названию и присваивает участнику."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            arch = self.svc.get_or_create_archetype_by_name(arch_name, is_custom=True)
            self.svc.set_participant_archetype(participant_id=participant_id, archetype_id=arch.id)
        except errors.ParticipantNotFound:
            return HandlerResult(PARTICIPANT_NOT_FOUND, is_alert=True)
        return HandlerResult(ADMIN_ARCH_SAVED.format(archetype_name=arch.name))

    def handle_tournament_status(self, tg_id: int) -> HandlerResult:
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        tournaments = self.svc.list_all_active_tournaments()
        if not tournaments:
            return HandlerResult(NO_ACTIVE_TOURNAMENT)
        blocks = [
            format_tournament_status(t.title, t.status.label_ru, self.svc.list_participants_for_tournament(t.id))
            for t in tournaments
        ]
        return HandlerResult("\n\n---\n\n".join(blocks))

    def handle_close_tournament(self, tg_id: int) -> HandlerResult:
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        self.svc.close_tournament(active.id)
        return HandlerResult(TOURNAMENT_CLOSED_MSG)

    def handle_create_tournament(
        self, tg_id: int, chat_id: int, title: str | None = None
    ) -> HandlerResult:
        """Создать новый турнир в текущем чате."""
        from core.schemas import TournamentCreate
        from datetime import datetime
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        if not title:
            title = f"Pauper {datetime.now().strftime('%Y-%m-%d')}"
        t = self.svc.create_tournament(TournamentCreate(title=title, chat_id=chat_id))
        return HandlerResult(f"✅ Турнир создан: «{t.title}» (id={t.id})")

    def handle_delete_tournament(self, tg_id: int) -> HandlerResult:
        """Удалить активный турнир вместе с участниками (для дебага, через /delete_tournament)."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        active, err = self._resolve_tournament()
        if err:
            return err
        title = active.title
        self.svc.delete_tournament(active.id)
        return HandlerResult(f"🗑 Турнир «{title}» удалён.")

    def handle_delete_tournament_prompt(
        self, tg_id: int, tournament_id: int
    ) -> HandlerResult:
        """Показывает запрос подтверждения удаления турнира."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            from services.utils import get_tournament
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        n = len(self.svc.list_participants_for_tournament(tournament_id))
        text = (
            f"⚠️ Удалить турнир «{t.title}»?\n"
            f"Будет удалено {n} участник(ов). Действие необратимо."
        )
        return HandlerResult(text, keyboard=delete_tournament_confirm_keyboard(tournament_id))

    def handle_delete_tournament_confirm(
        self, tg_id: int, tournament_id: int
    ) -> HandlerResult:
        """Выполняет удаление после подтверждения."""
        if not self._is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)
        try:
            from services.utils import get_tournament
            t = get_tournament(self.svc.db, tournament_id)
        except errors.TournamentNotFound:
            return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
        title = t.title
        self.svc.delete_tournament(tournament_id)
        return HandlerResult(f"🗑 Турнир «{title}» удалён.")
