# Telegram-обёртки для импорта из AetherHub

import logging
import re

from telegram import Message, Update, User
from telegram.ext import ContextTypes

from bot.handlers.aetherhub import AetherhubHandler
from bot.keyboards import aetherhub_confirm_keyboard
from bot.scheduler import get_clubs
from bot.telegram.common import parse_callback_ints
from bot.telegram.player import _player_handler
from bot.telegram.round_notify import send_round_notifications
from core.database import SessionLocal
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubTournamentData
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament

logger = logging.getLogger(__name__)

_aetherhub_service = AetherhubService()

USER_DATA_PENDING_AETHERHUB_URL = "pending_aetherhub_url_tournament_id"
USER_DATA_PENDING_IMPORT_TIME = "pending_import_time_tournament_id"
USER_DATA_AETHERHUB_URL = "aetherhub_url"
USER_DATA_AETHERHUB_DATA = "aetherhub_data"


def _aetherhub_handler(db=None) -> AetherhubHandler:
    if db:
        return AetherhubHandler(_aetherhub_service, AetherhubImportService(db), TournamentService(db))
    return AetherhubHandler(_aetherhub_service)


def _club_aetherhub_url(club_name: str | None) -> str | None:
    if not club_name:
        return None
    return next((c.aetherhub_url for c in get_clubs() if c.name == club_name), None)


async def callback_aetherhub_import_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📥/🔄 AetherHub»."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids

    db = SessionLocal()
    try:
        if not UserService(db).is_admin(user.id):
            await query.answer("Нет прав.", show_alert=True)
            return
        try:
            t = get_tournament(db, tournament_id)
            stored_url = t.aetherhub_url
            club_url = _club_aetherhub_url(t.club)
        except Exception:
            logger.exception("Failed to load tournament %s", tournament_id)
            stored_url = None
            club_url = None
    finally:
        db.close()

    await query.answer()

    if stored_url or club_url:
        status_msg = await query.message.reply_text("⏳ Загружаю данные с AetherHub…")
        try:
            result = _aetherhub_handler().handle_import_prompt(stored_url, club_url)
        except Exception as e:
            await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
            return
        if result:
            context.user_data[USER_DATA_AETHERHUB_URL] = result.data.url
            context.user_data[USER_DATA_AETHERHUB_DATA] = result.data
            await status_msg.edit_text(result.preview_text, reply_markup=aetherhub_confirm_keyboard(tournament_id))
            return
        await status_msg.edit_text("Турнир сегодня не найден автоматически.")

    context.user_data[USER_DATA_PENDING_AETHERHUB_URL] = tournament_id
    await query.message.reply_text(
        "Отправьте ссылку на турнир AetherHub\n(например: https://aetherhub.com/Tourney/RoundTourney/98984)"
    )


async def handle_pending_aetherhub_url(msg: Message, user: User, text: str, context) -> bool:
    """Обрабатывает ввод URL AetherHub. Возвращает True если обработал."""
    tournament_id = context.user_data.get(USER_DATA_PENDING_AETHERHUB_URL)
    if tournament_id is None:
        return False

    if "aetherhub.com/Tourney" not in text:
        await msg.reply_text("❌ Ожидается ссылка вида https://aetherhub.com/Tourney/RoundTourney/…")
        return True

    context.user_data.pop(USER_DATA_PENDING_AETHERHUB_URL)

    status_msg = await msg.reply_text("⏳ Загружаю данные с AetherHub…")
    try:
        fetch_result = _aetherhub_handler().handle_fetch_preview(text.strip(), "📥 Импорт AetherHub")
    except Exception as e:
        await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
        return True

    context.user_data[USER_DATA_AETHERHUB_URL] = text.strip()
    context.user_data[USER_DATA_AETHERHUB_DATA] = fetch_result.data
    await status_msg.edit_text(
        fetch_result.preview_text,
        reply_markup=aetherhub_confirm_keyboard(tournament_id),
    )
    return True


async def handle_pending_import_time(msg: Message, user: User, text: str, context) -> bool:
    """Обрабатывает ввод времени авто-импорта. Возвращает True если обработал."""
    tournament_id = context.user_data.get(USER_DATA_PENDING_IMPORT_TIME)
    if tournament_id is None:
        return False

    context.user_data.pop(USER_DATA_PENDING_IMPORT_TIME)
    text = text.strip()

    if text == "-":
        db = SessionLocal()
        try:
            TournamentService(db).set_import_time(tournament_id, None)
        finally:
            db.close()
        await msg.reply_text("⏰ Авто-импорт отключён.")
        return True

    if not re.match(r"^\d{1,2}:\d{2}$", text):
        await msg.reply_text("❌ Неверный формат. Введите время как HH:MM (например: 12:30)")
        return True

    parts = text.split(":")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await msg.reply_text("❌ Некорректное время. Часы 0–23, минуты 0–59.")
        return True

    time_str = f"{h:02d}:{m:02d}"
    db = SessionLocal()
    try:
        TournamentService(db).set_import_time(tournament_id, time_str)
    finally:
        db.close()
    await msg.reply_text(f"✅ Авто-импорт установлен на {time_str}")
    return True


async def callback_aetherhub_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение импорта."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids

    url = context.user_data.pop(USER_DATA_AETHERHUB_URL, None)
    data: AetherhubTournamentData | None = context.user_data.pop(USER_DATA_AETHERHUB_DATA, None)
    if not url or data is None:
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return

    await query.edit_message_text("⏳ Импортирую…")

    db = SessionLocal()
    try:
        result = _aetherhub_handler(db).handle_confirm_import(tournament_id, url, data)
    except Exception as e:
        logger.exception("Import failed for tournament %s", tournament_id)
        await query.edit_message_text(f"❌ Ошибка импорта: {e}")
        return
    finally:
        db.close()

    await query.edit_message_text(result.text)
    await query.answer()

    if result.new_round_numbers:
        db_notify = SessionLocal()
        try:
            # DataLens обязателен и здесь: без него ручной импорт слал бы уведомления без винрейта
            # (в отличие от scheduled-джоб, которые его передают) — см. bot/scheduler.py.
            await send_round_notifications(
                context.bot,
                db_notify,
                tournament_id,
                result.new_round_numbers,
                datalens_service=DataLensService(),
            )
        finally:
            db_notify.close()

    db2 = SessionLocal()
    try:
        card = _player_handler(db2).handle_tournament_select(tournament_id, tg_id=user.id)
    finally:
        db2.close()
    await query.message.reply_text(card.text, reply_markup=card.keyboard)


async def callback_set_import_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка для настройки авто-импорта AetherHub."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids

    db = SessionLocal()
    try:
        if not UserService(db).is_admin(user.id):
            await query.answer("Нет прав.", show_alert=True)
            return
    finally:
        db.close()

    context.user_data[USER_DATA_PENDING_IMPORT_TIME] = tournament_id
    await query.answer()
    await query.message.reply_text(
        "Отправьте время авто-импорта в формате HH:MM (например: 12:30)\nИли отправьте «-» чтобы отключить авто-импорт."
    )


async def callback_aetherhub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена импорта."""
    query = update.callback_query
    context.user_data.pop(USER_DATA_AETHERHUB_URL, None)
    context.user_data.pop(USER_DATA_AETHERHUB_DATA, None)
    await query.edit_message_text("Импорт отменён.")
    await query.answer()
