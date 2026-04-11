# Админ-панель

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Update
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
    PLAYER_NOT_FOUND,
    PLAYER_ADDED,
    TOURNAMENT_CLOSED_MSG,
    ADD_PLAYERS_USAGE,
)


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
        return HandlerResult(PLAYER_ADDED.format(
            username=username or first_name,
            archetype_name=archetype.name,
        ))
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult("Вы уже записаны на этот турнир.")
    except errors.TournamentInvalidState:
        return HandlerResult("Регистрация на этот турнир закрыта.")


def handle_add_player(
    db: Session,
    tg_id: int,
    target_username: str,
    deck_name: str,
) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    stmt = select(models.User).where(models.User.username == target_username)
    target_user = db.execute(stmt).scalar_one_or_none()
    if not target_user:
        return HandlerResult(PLAYER_NOT_FOUND.format(username=target_username))
    try:
        archetype = svc.get_or_create_archetype_by_name(deck_name)
        svc.register_participant(
            tournament_id=active.id,
            user_id=target_user.id,
            archetype_id=archetype.id,
            added_by_admin=True,
        )
        return HandlerResult(PLAYER_ADDED.format(
            username=target_username,
            archetype_name=archetype.name,
        ))
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult(f"@{target_username} уже записан на этот турнир.")
    except errors.TournamentInvalidState:
        return HandlerResult("Регистрация на этот турнир закрыта.")


def handle_add_players(
    db: Session,
    tg_id: int,
    lines: list[str],
) -> HandlerResult:
    if not _is_admin(db, tg_id):
        return HandlerResult(NOT_ADMIN)
    if not lines:
        return HandlerResult(ADD_PLAYERS_USAGE)
    svc = TournamentService(db)
    active, err = _resolve_tournament(svc)
    if err:
        return err
    results = []
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) < 2:
            results.append(f"⚠️ Пропущено: «{line}» — нет названия колоды")
            continue
        username = parts[0].lstrip("@")
        deck_name = parts[1].strip()
        stmt = select(models.User).where(models.User.username == username)
        target_user = db.execute(stmt).scalar_one_or_none()
        if not target_user:
            results.append(f"❌ @{username} — не найден (должен написать /start)")
            continue
        try:
            archetype = svc.get_or_create_archetype_by_name(deck_name)
            svc.register_participant(
                tournament_id=active.id,
                user_id=target_user.id,
                archetype_id=archetype.id,
                added_by_admin=True,
            )
            results.append(f"✅ @{username} — {archetype.name}")
        except errors.ParticipantAlreadyRegistered:
            results.append(f"⚠️ @{username} — уже записан")
        except errors.TournamentInvalidState:
            results.append(f"❌ @{username} — регистрация закрыта")
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
            username = (p.user.username or p.user.first_name or f"id{p.user.tg_id}") if p.user else "?"
            archetype = p.archetype.name if p.archetype else "не указана"
            confirmed = " ✅" if p.confirmed else ""
            lines.append(f"{i}. @{username} — {archetype}{confirmed}")
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
    args = context.args or []
    if len(args) < 2:
        await msg.reply_text("Использование: /add_player @username Название колоды")
        return
    username = args[0].lstrip("@")
    deck_name = " ".join(args[1:]).strip()
    db = SessionLocal()
    try:
        result = handle_add_player(db, user.id, username, deck_name)
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
    lines = [l.strip() for l in text.splitlines()[1:] if l.strip()]
    db = SessionLocal()
    try:
        result = handle_add_players(db, user.id, lines)
        await msg.reply_text(result.text)
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
