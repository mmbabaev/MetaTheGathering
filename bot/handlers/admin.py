# Админ-панель — чистая бизнес-логика

import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core import models
from services.tournament import TournamentService
from services.user import UserService
from services import errors
from bot.handlers.base import HandlerResult
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
    MULTIPLE_TOURNAMENTS_MSG,
    PLAYER_ADDED,
    TOURNAMENT_CLOSED_MSG,
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


def _is_admin(db: Session, tg_id: int) -> bool:
    if tg_id in settings.admin_ids:
        return True
    stmt = select(models.User).where(models.User.tg_id == tg_id)
    user = db.execute(stmt).scalar_one_or_none()
    return user is not None and (user.is_admin or user.is_superadmin)


# --- Pure business logic functions ---

def _resolve_tournament(svc: TournamentService):
    """Возвращает (tournament, error_result). Один из них None."""
    try:
        return svc.get_single_active_tournament(), None
    except errors.TournamentNotFound:
        return None, HandlerResult(NO_ACTIVE_TOURNAMENT)
    except errors.MultipleActiveTournaments:
        return None, HandlerResult(MULTIPLE_TOURNAMENTS_MSG)


def handle_add_me(
    db: Session,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    deck_name: str,
) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    if not deck_name:
        return HandlerResult(NO_DECK_NAME)
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    user_svc = UserService(db)
    try:
        db_user = user_svc.get_or_create(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        archetype = svc.get_or_create_archetype_by_name(deck_name)
        svc.register_participant(
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


def _player_display_label(username: str | None, first_name: str | None, tg_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return f"игрок {tg_id}"


def handle_add_player(
    db: Session,
    tg_id: int,
    *,
    target_tg_id: int,
    target_username: str | None,
    deck_name: str,
    target_first_name: str | None = None,
    target_last_name: str | None = None,
) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    user_svc = UserService(db)
    try:
        target_user = user_svc.get_or_create(
            tg_id=target_tg_id,
            username=target_username,
            first_name=target_first_name,
            last_name=target_last_name,
        )
        archetype = svc.get_or_create_archetype_by_name(deck_name)
        svc.register_participant(
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
    db: Session,
    tg_id: int,
    entries: list[tuple[int, str | None, str | None, str]],
) -> HandlerResult:
    """entries: (target_tg_id, username, first_name, deck_name) — после резолва в Telegram."""
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    if not entries:
        return HandlerResult("Нет данных для обработки.")
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    results = []
    user_svc = UserService(db)
    for target_tg_id, uname, fname, deck_name in entries:
        user_label = _player_display_label(uname, fname, target_tg_id)
        try:
            target_user = user_svc.get_or_create(
                tg_id=target_tg_id,
                username=uname,
                first_name=fname,
            )
            archetype = svc.get_or_create_archetype_by_name(deck_name)
            svc.register_participant(
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


def handle_tournament_status(db: Session, tg_id: int) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    svc = TournamentService(db)
    tournaments = svc.list_all_active_tournaments()
    if not tournaments:
        return HandlerResult(NO_ACTIVE_TOURNAMENT)
    blocks = [
        format_tournament_status(t.title, t.status.label_ru, svc.list_participants_for_tournament(t.id))
        for t in tournaments
    ]
    return HandlerResult("\n\n---\n\n".join(blocks))


def handle_close_tournament(db: Session, tg_id: int) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    svc.close_tournament(active.id)
    return HandlerResult(TOURNAMENT_CLOSED_MSG)
