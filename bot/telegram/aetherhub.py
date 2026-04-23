# Telegram-обёртки для импорта из AetherHub

import logging
import re

from telegram import Message, Update, User
from telegram.ext import ContextTypes

from bot.handlers.player import PlayerHandler
from bot.keyboards import aetherhub_confirm_keyboard
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services.aetherhub import AetherhubTournamentData, fetch_tournament
from services.aetherhub_import import AetherhubImportService
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament

logger = logging.getLogger(__name__)

USER_DATA_PENDING_AETHERHUB_URL = "pending_aetherhub_url_tournament_id"
USER_DATA_PENDING_IMPORT_TIME = "pending_import_time_tournament_id"
USER_DATA_AETHERHUB_URL = "aetherhub_url"
USER_DATA_AETHERHUB_DATA = "aetherhub_data"


def _build_preview(data: AetherhubTournamentData, header: str) -> str:
    rounds_summary = ", ".join(f"R{r.number}: {len(r.pairings) // 2} столов" for r in data.rounds)
    return (
        f"{header}\n\n"
        f"Игроков в стендингах: {len(data.players)}\n"
        f"Раунды: {rounds_summary}\n\n"
        f"Первые 5 игроков:\n"
        + "\n".join(f"  • {p}" for p in data.players[:5])
        + (f"\n  …ещё {len(data.players) - 5}" if len(data.players) > 5 else "")
    )


async def callback_aetherhub_import_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📥/🔄 AetherHub» — если URL уже привязан, обновляет импорт сразу."""
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
        except Exception:
            logger.exception("Failed to load tournament %s", tournament_id)
            stored_url = None
    finally:
        db.close()

    if stored_url:
        await query.answer()
        status_msg = await query.message.reply_text("⏳ Загружаю данные с AetherHub…")
        try:
            data = fetch_tournament(stored_url)
        except Exception as e:
            await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
            return
        context.user_data[USER_DATA_AETHERHUB_URL] = stored_url
        context.user_data[USER_DATA_AETHERHUB_DATA] = data
        await status_msg.edit_text(
            _build_preview(data, "🔄 Обновление AetherHub"),
            reply_markup=aetherhub_confirm_keyboard(tournament_id),
        )
    else:
        context.user_data[USER_DATA_PENDING_AETHERHUB_URL] = tournament_id
        await query.answer()
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
        data = fetch_tournament(text.strip())
    except Exception as e:
        await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
        return True

    context.user_data[USER_DATA_AETHERHUB_URL] = text.strip()
    context.user_data[USER_DATA_AETHERHUB_DATA] = data

    await status_msg.edit_text(
        _build_preview(data, "📥 Импорт AetherHub"),
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
        result = AetherhubImportService(db).import_tournament(tournament_id, data)
        TournamentService(db).set_aetherhub_url(tournament_id, url)
    except Exception as e:
        logger.exception("Import failed for tournament %s", tournament_id)
        await query.edit_message_text(f"❌ Ошибка импорта: {e}")
        return
    finally:
        db.close()

    lines = [
        "✅ Импорт завершён",
        f"Зарегистрировано новых: {result.registered}",
        f"Уже были: {result.already_registered}",
        f"Паринги сохранены: {result.pairings_saved}",
    ]
    if result.created_names:
        lines.append(
            f"Созданы как новые игроки ({len(result.created_names)}): "
            + ", ".join(result.created_names[:5])
            + ("…" if len(result.created_names) > 5 else "")
        )

    await query.edit_message_text("\n".join(lines))
    await query.answer()

    db2 = SessionLocal()
    try:
        card = PlayerHandler(TournamentService(db2), UserService(db2), ArchetypeService(db2)).handle_tournament_select(
            tournament_id, tg_id=user.id, has_pairings=True
        )
    finally:
        db2.close()
    await query.message.reply_text(card.text, reply_markup=card.keyboard)


async def callback_aetherhub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена импорта."""
    query = update.callback_query
    context.user_data.pop(USER_DATA_AETHERHUB_URL, None)
    context.user_data.pop(USER_DATA_AETHERHUB_DATA, None)
    await query.edit_message_text("Импорт отменён.")
    await query.answer()
