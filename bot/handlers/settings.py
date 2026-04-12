# /settings — управление профилем пользователя

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from services.tournament import TournamentService
from bot.handlers.base import HandlerResult
from bot.keyboards import settings_keyboard, CB_SETTINGS_NAME
from bot.messages import SETTINGS_MENU, SETTINGS_CHANGE_NAME_PROMPT, NAME_SAVED

USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"


# --- Pure logic ---

def handle_settings(db: Session, tg_id: int) -> HandlerResult:
    """Показывает меню настроек с кнопкой смены имени."""
    svc = TournamentService(db)
    user = svc.get_user_by_tg_id(tg_id)
    name_parts = []
    if user and user.first_name:
        name_parts.append(user.first_name)
    if user and user.last_name:
        name_parts.append(user.last_name)
    current = " ".join(name_parts) if name_parts else "не указано"
    text = f"{SETTINGS_MENU}\n\nВаше имя: {current}"
    return HandlerResult(text, keyboard=settings_keyboard())


def handle_settings_name_text(db: Session, tg_id: int, name_text: str) -> HandlerResult:
    """Сохраняет новое имя пользователя."""
    parts = name_text.strip().split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None
    svc = TournamentService(db)
    svc.update_user_name(tg_id, first_name, last_name)
    full_name = f"{first_name} {last_name}" if last_name else first_name
    return HandlerResult(NAME_SAVED.format(full_name=full_name))


# --- Telegram wrappers ---

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = handle_settings(db, user.id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_settings_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
    await query.edit_message_text(SETTINGS_CHANGE_NAME_PROMPT)
    await query.answer()
