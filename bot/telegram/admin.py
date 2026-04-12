# Telegram-обёртки для admin-хендлеров

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from core.config import settings
from core.database import SessionLocal
from bot.handlers.admin import (
    handle_add_me,
    handle_add_player,
    handle_add_players,
    handle_tournament_status,
    handle_close_tournament,
    parse_add_player_command,
    parse_bulk_player_line,
)
from bot.messages import TELEGRAM_USER_LOOKUP_FAILED, ADD_PLAYERS_USAGE


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
    raw_lines = [line.strip() for line in text.splitlines()[1:] if line.strip()]
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
