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
from bot.keyboards import fill_deck_keyboard, notify_confirm_keyboard
from bot.telegram.common import log_event as _log, parse_callback_ints

logger = logging.getLogger(__name__)

_POLL_QUESTION = "Пойдёшь на турнир?"
_POLL_OPTIONS = ["Пойду", "Не пойду"]
_DM_NO_DECK = "Привет! Ты записался на турнир, но ещё не выбрал колоду. Зайди в /tournaments и заполни её."


def _poll_message_link(chat_id: int, message_id: int, chat_username: str | None = None) -> str | None:
    """Ссылка на сообщение в группе.
    Публичная группа (есть username): t.me/{username}/{message_id}
    Супергруппа без username (-100XXXXX): t.me/c/{id}/{message_id}
    Обычная группа: None
    """
    if chat_username:
        return f"https://t.me/{chat_username}/{message_id}"
    bare_id = str(abs(chat_id))
    if not bare_id.startswith("100") or len(bare_id) < 12:
        return None
    return f"https://t.me/c/{bare_id[3:]}/{message_id}"


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

        try:
            chat_info = await context.bot.get_chat(chat_id)
            chat_username = chat_info.username
        except Exception:
            chat_username = None

        PollService(db).create_poll(
            tournament_id=tournament_id,
            chat_id=chat_id,
            tg_poll_id=msg.poll.id,
            message_id=msg.message_id,
            chat_username=chat_username,
        )
        _log("create_poll", user, tournament_id=tournament_id)
        poll_link = _poll_message_link(chat_id, msg.message_id, chat_username)
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


def _build_notify_preview(
    poll_svc: PollService,
    tournament_id: int,
    t_chat_id: int,
    t_title: str,
) -> tuple[str, list[int]] | None:
    """Строит текст превью рассылки. Возвращает (text, voter_ids) или None если некому слать."""
    latest_poll = poll_svc.get_latest_poll_for_chat(t_chat_id)
    poll_id = latest_poll.id if latest_poll else None

    voters = poll_svc.get_yes_voters_without_deck(tournament_id, poll_id=poll_id)
    if not voters:
        return None

    yes_count, no_count = (
        poll_svc.get_poll_stats(poll_id) if poll_id else (0, 0)
    )

    poll_link = (
        _poll_message_link(latest_poll.chat_id, latest_poll.message_id, latest_poll.chat_username)
        if latest_poll else None
    )

    names = poll_svc.get_voter_display_names(voters)
    player_list = "\n".join(f"  • {names[tg_id]}" for tg_id in voters)

    lines = [
        f"📊 Голосование «{t_title}»:",
        f"  ✅ Пойду: {yes_count}   ❌ Не пойду: {no_count}",
    ]
    if poll_link:
        lines.append(f"  🔗 {poll_link}")
    lines += [
        "",
        f"Получат сообщение ({len(voters)}):",
        player_list,
    ]
    return "\n".join(lines), voters


async def callback_notify_no_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📣 Без колоды» — показывает превью рассылки с запросом подтверждения."""
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
        result = _build_notify_preview(PollService(db), tournament_id, t.chat_id, t.title)
        if result is None:
            await query.answer("Все «пойду» уже заполнили колоду.", show_alert=True)
            return

        preview_text, _ = result
        await query.edit_message_text(preview_text, reply_markup=notify_confirm_keyboard(tournament_id))
        await query.answer()
    finally:
        db.close()


async def callback_notify_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение рассылки — реально отправляет DM."""
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
        poll_svc = PollService(db)
        latest_poll = poll_svc.get_latest_poll_for_chat(t.chat_id)
        poll_id = latest_poll.id if latest_poll else None
        voters = poll_svc.get_yes_voters_without_deck(tournament_id, poll_id=poll_id)

        if not voters:
            await query.edit_message_text("Уже нечего отправлять — все заполнили колоду.")
            await query.answer()
            return

        sent = 0
        notified_ids = []
        keyboard = fill_deck_keyboard(tournament_id)
        for tg_id in voters:
            if not _is_notify_allowed(tg_id):
                logger.info(f"[poll] skip notify tg_id={tg_id} (not in allowed list)")
                continue
            try:
                await context.bot.send_message(chat_id=tg_id, text=_DM_NO_DECK, reply_markup=keyboard)
                notified_ids.append(tg_id)
                sent += 1
            except Exception as e:
                logger.warning(f"[poll] Could not DM tg_id={tg_id}: {e}")

        if notified_ids:
            poll_svc.mark_notified(tournament_id, notified_ids)

        _log("notify_no_deck", user, tournament_id=tournament_id, sent=sent, total=len(voters))
        await query.edit_message_text(f"✅ Отправлено {sent} из {len(voters)} игроков.")
        await query.answer()
    finally:
        db.close()


async def callback_notify_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена рассылки."""
    query = update.callback_query
    await query.edit_message_text("Рассылка отменена.")
    await query.answer()
