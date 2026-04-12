# Админ-панель

import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from core.config import settings
from core.database import SessionLocal
from core import models
from services.tournament import TournamentService
from services import errors
from bot.handlers.base import HandlerResult
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
    MULTIPLE_TOURNAMENTS_MSG,
    PLAYER_ADDED,
    TELEGRAM_USER_LOOKUP_FAILED,
    TOURNAMENT_CLOSED_MSG,
    ADD_PLAYERS_USAGE,
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
    try:
        db_user = svc.get_or_create_user(
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
    try:
        target_user = svc.get_or_create_user(
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
    for target_tg_id, uname, fname, deck_name in entries:
        user_label = _player_display_label(uname, fname, target_tg_id)
        try:
            target_user = svc.get_or_create_user(
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
    blocks = []
    for t in tournaments:
        participants = svc.list_participants_for_tournament(t.id)
        lines = [
            f"Турнир: {t.title}",
            f"Статус: {t.status.label_ru}",
            f"Участники ({len(participants)}):",
        ]
        for i, p in enumerate(participants, 1):
            if p.user:
                name_parts = [n for n in (p.user.first_name, p.user.last_name) if n]
                full_name = " ".join(name_parts) if name_parts else f"id{p.user.tg_id}"
                username_hint = f" (@{p.user.username})" if p.user.username else ""
                display = f"{full_name}{username_hint}"
            else:
                display = "?"
            archetype = p.archetype.name if p.archetype else "не указана"
            confirmed = " ✅" if p.confirmed else ""
            lines.append(f"{i}. {display} — {archetype}{confirmed}")
        blocks.append("\n".join(lines))
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


# --- Telegram command wrappers ---

async def cmd_add_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_me <deck_name> — регистрирует администратора в текущем турнире."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    deck_name = " ".join(context.args or []).strip()
    db = SessionLocal()
    try:
        result = handle_add_me(db, user.id, user.username, user.first_name, user.last_name, deck_name)
        await msg.reply_text(result.text)
    finally:
        db.close()


async def cmd_add_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_player @username <deck_name> — добавляет игрока по username."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    bot_name = context.bot.username if context.bot else None
    parsed = parse_add_player_command(msg.text or "", bot_name)
    if not parsed:
        await msg.reply_text("Использование: /add_player @username Название колоды")
        return
    username, deck_name = parsed
    if settings.DEBUG:
        target_tg_id = 0
        target_first_name = None
        target_last_name = None
    else:
        try:
            chat = await context.bot.get_chat(f"@{username}")
        except TelegramError:
            await msg.reply_text(TELEGRAM_USER_LOOKUP_FAILED.format(username=username))
            return
        if chat.type != ChatType.PRIVATE:
            await msg.reply_text(
                f"❌ @{username} — укажите @username человека (не группу или канал)."
            )
            return
        target_tg_id = chat.id
        target_first_name = chat.first_name
        target_last_name = chat.last_name
    db = SessionLocal()
    try:
        result = handle_add_player(
            db,
            user.id,
            target_tg_id=target_tg_id,
            target_username=username,
            deck_name=deck_name,
            target_first_name=target_first_name,
            target_last_name=target_last_name,
        )
        await msg.reply_text(result.text)
    finally:
        db.close()


async def cmd_add_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_players — массовое добавление игроков (по одному на строку: @username Колода)."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    text = msg.text or ""
    raw_lines = [l.strip() for l in text.splitlines()[1:] if l.strip()]
    if not raw_lines:
        await msg.reply_text(ADD_PLAYERS_USAGE)
        return

    fragments: list[str] = []
    entries: list[tuple[int, str | None, str | None, str]] = []
    for line in raw_lines:
        pl = parse_bulk_player_line(line)
        if not pl:
            fragments.append(f"⚠️ Пропущено: «{line}» — нет названия колоды")
            continue
        uname, deck_name = pl
        try:
            chat = await context.bot.get_chat(f"@{uname}")
        except TelegramError:
            fragments.append(f"❌ @{uname} — не найден в Telegram")
            continue
        if chat.type != ChatType.PRIVATE:
            fragments.append(f"❌ @{uname} — укажите @username человека (не группу или канал)")
            continue
        entries.append((chat.id, chat.username, chat.first_name, deck_name))

    db = SessionLocal()
    try:
        if not entries:
            body = "\n".join(fragments) if fragments else ADD_PLAYERS_USAGE
            await msg.reply_text(body)
            return
        result = handle_add_players(db, user.id, entries)
        out = ("\n".join(fragments) + "\n" + result.text).strip() if fragments else result.text
        await msg.reply_text(out)
    finally:
        db.close()


async def cmd_tournament_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tournament_status — все активные турниры и их участники."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = handle_tournament_status(db, user.id)
        await msg.reply_text(result.text)
    finally:
        db.close()


async def cmd_close_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/close_tournament — закрывает текущий турнир."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = handle_close_tournament(db, user.id)
        await msg.reply_text(result.text)
    finally:
        db.close()
