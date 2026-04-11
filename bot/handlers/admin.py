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
from bot.messages import (
    NOT_ADMIN,
    NO_DECK_NAME,
    NO_ACTIVE_TOURNAMENT,
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


def _status_display(status: models.TournamentStatus) -> str:
    return {
        models.TournamentStatus.REGISTRATION: "Регистрация",
        models.TournamentStatus.ONGOING: "Идёт",
        models.TournamentStatus.VOTING: "Голосование",
        models.TournamentStatus.CLOSED: "Завершён",
    }.get(status, status.value)


async def cmd_add_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_me <deck_name> — регистрирует администратора в текущем турнире."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    db = SessionLocal()
    try:
        if not _is_admin(db, user.id):
            await msg.reply_text(NOT_ADMIN)
            return

        deck_name = " ".join(context.args or []).strip()
        if not deck_name:
            await msg.reply_text(NO_DECK_NAME)
            return

        chat_id = update.effective_chat.id
        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(chat_id)
        if not active:
            await msg.reply_text(NO_ACTIVE_TOURNAMENT)
            return

        db_user = svc.get_or_create_user(
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        archetype = svc.get_or_create_archetype_by_name(deck_name)
        svc.register_participant(
            tournament_id=active.id,
            user_id=db_user.id,
            archetype_id=archetype.id,
            added_by_admin=True,
        )
        await msg.reply_text(PLAYER_ADDED.format(
            username=user.username or user.first_name,
            archetype_name=archetype.name,
        ))
    except errors.ParticipantAlreadyRegistered:
        await msg.reply_text("Вы уже записаны на этот турнир.")
    except errors.TournamentInvalidState:
        await msg.reply_text("Регистрация на этот турнир закрыта.")
    finally:
        db.close()


async def cmd_add_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_player @username <deck_name> — добавляет игрока по username."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    db = SessionLocal()
    try:
        if not _is_admin(db, user.id):
            await msg.reply_text(NOT_ADMIN)
            return

        args = context.args or []
        if len(args) < 2:
            await msg.reply_text("Использование: /add_player @username Название колоды")
            return

        username = args[0].lstrip("@")
        deck_name = " ".join(args[1:]).strip()

        chat_id = update.effective_chat.id
        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(chat_id)
        if not active:
            await msg.reply_text(NO_ACTIVE_TOURNAMENT)
            return

        stmt = select(models.User).where(models.User.username == username)
        target_user = db.execute(stmt).scalar_one_or_none()
        if not target_user:
            await msg.reply_text(PLAYER_NOT_FOUND.format(username=username))
            return

        archetype = svc.get_or_create_archetype_by_name(deck_name)
        svc.register_participant(
            tournament_id=active.id,
            user_id=target_user.id,
            archetype_id=archetype.id,
            added_by_admin=True,
        )
        await msg.reply_text(PLAYER_ADDED.format(
            username=username,
            archetype_name=archetype.name,
        ))
    except errors.ParticipantAlreadyRegistered:
        await msg.reply_text(f"@{username} уже записан на этот турнир.")
    except errors.TournamentInvalidState:
        await msg.reply_text("Регистрация на этот турнир закрыта.")
    finally:
        db.close()


async def cmd_add_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_players — массовое добавление игроков (по одному на строку: @username Колода)."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    db = SessionLocal()
    try:
        if not _is_admin(db, user.id):
            await msg.reply_text(NOT_ADMIN)
            return

        # Парсим строки после первой (сама команда)
        text = msg.text or ""
        lines = [l.strip() for l in text.splitlines()[1:] if l.strip()]
        if not lines:
            await msg.reply_text(ADD_PLAYERS_USAGE)
            return

        chat_id = update.effective_chat.id
        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(chat_id)
        if not active:
            await msg.reply_text(NO_ACTIVE_TOURNAMENT)
            return

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

        await msg.reply_text("\n".join(results) if results else "Нет данных для обработки.")
    finally:
        db.close()


async def cmd_tournament_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tournament_status — текущий турнир и список участников."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    db = SessionLocal()
    try:
        if not _is_admin(db, user.id):
            await msg.reply_text(NOT_ADMIN)
            return

        chat_id = update.effective_chat.id
        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(chat_id)
        if not active:
            await msg.reply_text(NO_ACTIVE_TOURNAMENT)
            return

        participants = svc.list_participants_for_tournament(active.id)
        lines = [
            f"Турнир: {active.title}",
            f"Статус: {_status_display(active.status)}",
            f"Участники ({len(participants)}):",
        ]
        for i, p in enumerate(participants, 1):
            username = (p.user.username or p.user.first_name or f"id{p.user.tg_id}") if p.user else "?"
            archetype = p.archetype.name if p.archetype else "?"
            lines.append(f"{i}. @{username} — {archetype}")

        await msg.reply_text("\n".join(lines))
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
        if not _is_admin(db, user.id):
            await msg.reply_text(NOT_ADMIN)
            return

        chat_id = update.effective_chat.id
        svc = TournamentService(db)
        active = svc.get_active_tournament_for_chat(chat_id)
        if not active:
            await msg.reply_text(NO_ACTIVE_TOURNAMENT)
            return

        svc.close_tournament(active.id)
        await msg.reply_text(TOURNAMENT_CLOSED_MSG)
    finally:
        db.close()
