# Telegram-обёртки для poll-фичи

import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.config import settings
from core.database import SessionLocal
from services.user import UserService
from services.tournament import TournamentService
from services.archetype import ArchetypeService
from services.poll import PollService
from services.utils import get_tournament
from bot.handlers.admin import AdminHandler
from bot.keyboards import fill_deck_keyboard
from bot.telegram.common import log_event as _log, parse_callback_ints

logger = logging.getLogger(__name__)

_POLL_QUESTION = "Пойдёшь на турнир?"
_POLL_OPTIONS = ["Пойду", "Не пойду"]
_DM_NO_DECK = "Привет! Ты записался на турнир, но ещё не выбрал колоду. Зайди в /tournaments и заполни её."


def _poll_message_link(chat_id: int, message_id: int) -> str | None:
    """Ссылка на сообщение в группе. Работает только для супергрупп (chat_id < -1000000000)."""
    if chat_id >= 0:
        return None
    # Супергруппы: chat_id вида -100XXXXXXXXX → убираем -100
    bare_id = str(abs(chat_id))
    if bare_id.startswith("100"):
        bare_id = bare_id[3:]
    return f"https://t.me/c/{bare_id}/{message_id}"


def _admin_handler(db) -> AdminHandler:
    return AdminHandler(TournamentService(db), UserService(db), ArchetypeService(db))


def _is_notify_allowed(tg_user_id: int) -> bool:
    allowed = settings.notify_allowed_ids
    return allowed is None or tg_user_id in allowed


async def callback_create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📊 Голосование» — создаёт Telegram-опрос для турнира."""
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
        result = _admin_handler(db).handle_create_poll(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return

        t = get_tournament(db, tournament_id)
        chat_id = t.chat_id
        tournament_title = t.title

        from telegram.error import TelegramError
        try:
            msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=f"{_POLL_QUESTION} ({tournament_title})",
                options=_POLL_OPTIONS,
                is_anonymous=False,
            )
        except TelegramError as e:
            logger.error(f"[poll] send_poll failed for chat_id={chat_id}: {e}")
            await query.answer(f"❌ Не удалось создать опрос в чате {chat_id}: {e}", show_alert=True)
            return

        PollService(db).create_poll(
            tournament_id=tournament_id,
            chat_id=chat_id,
            tg_poll_id=msg.poll.id,
            message_id=msg.message_id,
        )
        _log("create_poll", user, tournament_id=tournament_id)
        poll_link = _poll_message_link(chat_id, msg.message_id)
        await query.answer()
        await query.message.reply_text(
            f"✅ Опрос создан!\n{poll_link}" if poll_link else "✅ Опрос создан!"
        )
    finally:
        db.close()


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обновление poll_answer — сохраняет голос пользователя."""
    poll_answer = update.poll_answer
    if not poll_answer:
        return

    tg_user_id = poll_answer.user.id
    if not _is_notify_allowed(tg_user_id):
        return

    option_ids = poll_answer.option_ids
    if not option_ids:
        return
    choice = option_ids[0]  # 0 = пойду, 1 = не пойду

    db = SessionLocal()
    try:
        poll = PollService(db).get_poll_by_tg_id(poll_answer.poll_id)
        if poll is None:
            return
        PollService(db).upsert_vote(poll.id, tg_user_id, choice)
    finally:
        db.close()


async def callback_notify_no_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📣 Без колоды» — отправляет DM игрокам, проголосовавшим «пойду» без колоды."""
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
        user_svc = UserService(db)
        if not user_svc.is_admin(user.id):
            await query.answer("Нет прав.", show_alert=True)
            return

        # Берём последний опрос для чата турнира (fallback на tournament_id если опроса нет)
        t = get_tournament(db, tournament_id)
        poll_svc = PollService(db)
        latest_poll = poll_svc.get_latest_poll_for_chat(t.chat_id)
        effective_tournament_id = latest_poll.tournament_id if latest_poll else tournament_id

        voters = poll_svc.get_yes_voters_without_deck(effective_tournament_id)
        if not voters:
            await query.answer("Все «пойду» уже заполнили колоду.", show_alert=True)
            return

        sent = 0
        notified_ids = []
        keyboard = fill_deck_keyboard(effective_tournament_id)
        for tg_id in voters:
            if not _is_notify_allowed(tg_id):
                logger.info(f"[poll] skip notify tg_id={tg_id} (not in allowed list)")
                continue
            try:
                await context.bot.send_message(
                    chat_id=tg_id, text=_DM_NO_DECK, reply_markup=keyboard
                )
                notified_ids.append(tg_id)
                sent += 1
            except Exception as e:
                logger.warning(f"[poll] Could not DM tg_id={tg_id}: {e}")

        if notified_ids:
            poll_svc.mark_notified(effective_tournament_id, notified_ids)

        _log("notify_no_deck", user, tournament_id=tournament_id, sent=sent, total=len(voters))
        await query.answer(f"Отправлено {sent} из {len(voters)} игроков.")
    finally:
        db.close()
