# Telegram-обёртки для импорта из AetherHub

import logging

from telegram import Update, Message, User
from telegram.ext import ContextTypes

from core.database import SessionLocal
from services.user import UserService
from services.tournament import TournamentService
from services.aetherhub import fetch_tournament
from services.aetherhub_import import AetherhubImportService
from services.utils import get_tournament
from bot.keyboards import aetherhub_confirm_keyboard
from bot.telegram.common import parse_callback_ints

logger = logging.getLogger(__name__)

USER_DATA_PENDING_AETHERHUB_URL = "pending_aetherhub_url_tournament_id"
USER_DATA_AETHERHUB_URL = "aetherhub_url"


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
        t = get_tournament(db, tournament_id)
        stored_url = t.aetherhub_url
    finally:
        db.close()

    if stored_url:
        # Auto-fetch with stored URL — skip URL input, go straight to confirm
        await query.answer()
        status_msg = await query.message.reply_text("⏳ Загружаю данные с AetherHub…")
        try:
            data = fetch_tournament(stored_url)
        except Exception as e:
            await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
            return
        context.user_data[USER_DATA_AETHERHUB_URL] = stored_url
        rounds_summary = ", ".join(f"R{r.number}: {len(r.pairings) // 2} столов" for r in data.rounds)
        preview = (
            f"🔄 Обновление AetherHub\n\n"
            f"Игроков в стендингах: {len(data.players)}\n"
            f"Раунды: {rounds_summary}\n\n"
            f"Первые 5 игроков:\n"
            + "\n".join(f"  • {p}" for p in data.players[:5])
            + (f"\n  …ещё {len(data.players) - 5}" if len(data.players) > 5 else "")
        )
        await status_msg.edit_text(preview, reply_markup=aetherhub_confirm_keyboard(tournament_id))
    else:
        context.user_data[USER_DATA_PENDING_AETHERHUB_URL] = tournament_id
        await query.answer()
        await query.message.reply_text(
            "Отправьте ссылку на турнир AetherHub\n"
            "(например: https://aetherhub.com/Tourney/RoundTourney/98984)"
        )


async def handle_pending_aetherhub_url(msg: Message, user: User, text: str, context) -> bool:
    """Обрабатывает ввод URL AetherHub. Возвращает True если обработал."""
    tournament_id = context.user_data.get(USER_DATA_PENDING_AETHERHUB_URL)
    if tournament_id is None:
        return False

    if "aetherhub.com/Tourney" not in text:
        await msg.reply_text(
            "❌ Ожидается ссылка вида https://aetherhub.com/Tourney/RoundTourney/…"
        )
        return True

    context.user_data.pop(USER_DATA_PENDING_AETHERHUB_URL)

    status_msg = await msg.reply_text("⏳ Загружаю данные с AetherHub…")
    try:
        data = fetch_tournament(text.strip())
    except Exception as e:
        await status_msg.edit_text(f"❌ Не удалось загрузить турнир: {e}")
        return True

    context.user_data[USER_DATA_AETHERHUB_URL] = text.strip()

    rounds_summary = ", ".join(f"R{r.number}: {len(r.pairings) // 2} столов" for r in data.rounds)
    preview = (
        f"📥 Импорт AetherHub\n\n"
        f"Игроков в стендингах: {len(data.players)}\n"
        f"Раунды: {rounds_summary}\n\n"
        f"Первые 5 игроков:\n"
        + "\n".join(f"  • {p}" for p in data.players[:5])
        + (f"\n  …ещё {len(data.players) - 5}" if len(data.players) > 5 else "")
    )

    await status_msg.edit_text(preview, reply_markup=aetherhub_confirm_keyboard(tournament_id))
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
    if not url:
        await query.answer("Сессия истекла, начните заново.", show_alert=True)
        return

    await query.edit_message_text("⏳ Импортирую…")
    try:
        data = fetch_tournament(url)
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка загрузки: {e}")
        return

    db = SessionLocal()
    try:
        result = AetherhubImportService(db).import_tournament(tournament_id, data)
        TournamentService(db).set_aetherhub_url(tournament_id, url)
    finally:
        db.close()

    lines = [
        "✅ Импорт завершён",
        f"Зарегистрировано новых: {result.registered}",
        f"Уже были: {result.already_registered}",
        f"Паринги сохранены: {result.pairings_saved}",
    ]
    if result.created_names:
        lines.append(f"Созданы как новые игроки ({len(result.created_names)}): "
                     + ", ".join(result.created_names[:5])
                     + ("…" if len(result.created_names) > 5 else ""))

    await query.edit_message_text("\n".join(lines))
    await query.answer()

    from services.tournament import TournamentService
    from services.archetype import ArchetypeService
    from services.user import UserService
    from bot.handlers.player import PlayerHandler
    db2 = SessionLocal()
    try:
        card = PlayerHandler(
            TournamentService(db2), UserService(db2), ArchetypeService(db2)
        ).handle_tournament_select(tournament_id, tg_id=user.id, has_pairings=True)
    finally:
        db2.close()
    await query.message.reply_text(card.text, reply_markup=card.keyboard)


async def callback_aetherhub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена импорта."""
    query = update.callback_query
    context.user_data.pop(USER_DATA_AETHERHUB_URL, None)
    await query.edit_message_text("Импорт отменён.")
    await query.answer()
