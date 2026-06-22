# Telegram-обёртки для admin-хендлеров

import html
import io
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.handlers.admin import parse_bulk_player_line
from bot.keyboards import (
    admin_more_keyboard,
    export_menu_keyboard,
    reveal_decks_confirm_keyboard,
)
from bot.messages import ADD_PLAYERS_USAGE, BULK_ADD_PROMPT
from bot.scheduler import format_schedule_text
from bot.telegram.common import log_event as _log
from bot.telegram.common import parse_callback_ints
from bot.telegram.player import (
    USER_DATA_OPPONENTS_MODE,
    USER_DATA_PENDING_ADMIN_CUSTOM_ARCH,
    USER_DATA_PENDING_BULK_ADD,
    USER_DATA_PENDING_META_IMPORT,
    _admin_handler,
    _player_handler,
)
from bot.telegram.round_notify import send_debug_round_notifications
from core.config import app_cfg, settings
from core.database import SessionLocal
from core.models import TournamentStatus
from services import errors as svc_errors
from services.datalens import DataLensService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament


async def callback_meta_import_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📋 Импорт по таблице» — показывает инструкцию и ждёт текст."""
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
        result = _admin_handler(db).handle_meta_import_start(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        if context.user_data is None:
            context.user_data = {}
        context.user_data[USER_DATA_PENDING_META_IMPORT] = tournament_id
        _log("meta_import_start", user, tournament_id=tournament_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_bulk_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «➕ Добавить участников» на карточке турнира."""
    query = update.callback_query
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    user = update.effective_user
    _log("bulk_add_start", user, tournament_id=tournament_id)
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_BULK_ADD] = tournament_id
    await query.edit_message_text(BULK_ADD_PROMPT)
    await query.answer()


async def callback_pick_participant_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Нажатие на участника в admin status → показывает выбор архетипа."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (participant_id,) = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_pick_participant_arch(user.id, participant_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_set_participant_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выбор конкретного архетипа для участника."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, archetype_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_set_participant_arch(user.id, participant_id, archetype_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("admin_set_arch", user, participant_id=participant_id, archetype_id=archetype_id)

        opponents_tournament_id = (context.user_data or {}).get(USER_DATA_OPPONENTS_MODE)
        if opponents_tournament_id is not None:
            await query.edit_message_text(result.text)
            await query.answer()
            opponents_result = _admin_handler(db).handle_fill_opponents(user.id, opponents_tournament_id)
            if opponents_result.is_alert:
                context.user_data.pop(USER_DATA_OPPONENTS_MODE, None)
                card = _player_handler(db).handle_tournament_select(opponents_tournament_id, tg_id=user.id)
                await query.message.reply_text(card.text, reply_markup=card.keyboard)
            else:
                await query.message.reply_text(opponents_result.text, reply_markup=opponents_result.keyboard)
        else:
            await query.edit_message_text(result.text, reply_markup=result.keyboard)
            await query.answer()
    finally:
        db.close()


async def callback_pick_participant_arch_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«... ещё» в admin pick arch — разворачивает полный список архетипов."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (participant_id,) = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_pick_participant_arch_more(user.id, participant_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_participant_custom_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«Свой вариант» — ждём текст с названием архетипа."""
    query = update.callback_query
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (participant_id,) = ids
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_ADMIN_CUSTOM_ARCH] = participant_id
    await query.edit_message_text("Напишите название архетипа:")
    await query.answer()


async def callback_admin_show_filled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «Показать заполненных (N)» — разворачивает список заполненных участников."""
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
        result = _admin_handler(db).handle_admin_show_filled(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
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
        result = _admin_handler(db).handle_add_players(user.id, entries)
        out = ("\n".join(fragments) + "\n" + result.text).strip() if fragments else result.text
        await msg.reply_text(out)
    finally:
        db.close()


async def cmd_archive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/archive — последние закрытые турниры."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_archive(user.id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
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
        result = _admin_handler(db).handle_tournament_status(user.id)
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
        result = _admin_handler(db).handle_close_tournament(user.id)
        if not result.is_alert:
            _log("close_tournament", user)
        await msg.reply_text(result.text)
    finally:
        db.close()


async def cmd_create_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/create_tournament [название] — создаёт турнир. В личке дефолт — чат Единорога."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    if msg.chat.type == ChatType.PRIVATE:
        chat_id = app_cfg.edinorog_chat_id or msg.chat_id
    else:
        chat_id = msg.chat_id
    title = " ".join(context.args or []).strip() or None
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_create_tournament(user.id, chat_id, title)
        if result.is_alert:
            await msg.reply_text(result.text)
            return
        _log("create_tournament", user, chat_id=chat_id, title=title)
        await msg.reply_text(result.text)
        card = _player_handler(db).handle_tournament_select(result.tournament_id, tg_id=user.id)
        await msg.reply_text(card.text, reply_markup=card.keyboard)
    finally:
        db.close()


async def cmd_delete_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delete_tournament — удаляет активный турнир и всех участников (дебаг)."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_delete_tournament(user.id)
        await msg.reply_text(result.text)
    finally:
        db.close()


async def callback_export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📈 Выгрузка» — открывает подменю экспорта."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    await query.answer()
    await query.edit_message_text("Выберите формат выгрузки:", reply_markup=export_menu_keyboard(tournament_id))


async def callback_export_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «👥 Список игроков» — отправляет plain-text список имён."""
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
        result = _admin_handler(db).handle_export_players(user.id, tournament_id)
        if result is None:
            # Отвечаем только здесь алертом — раньше query.answer() звался выше,
            # из-за чего этот алерт «Нет прав» не показывался (повторный answer игнорится).
            await query.answer("Нет прав или турнир не найден.", show_alert=True)
            return
        await query.answer()
        # html.escape: имена игроков могут содержать <, >, & — без экранирования
        # parse_mode=HTML падал с ошибкой парсинга и список не отправлялся.
        await query.message.reply_text(f"<pre>{html.escape(result)}</pre>", parse_mode="HTML")
        _log("export_players", user, tournament_id=tournament_id)
    finally:
        db.close()


async def callback_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📊 Выгрузка Excel» — отправляет файл участников (+ паринги, если есть)."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    await query.answer("Генерирую файл…")
    db = SessionLocal()
    try:
        files = _admin_handler(db).handle_export_excel(user.id, tournament_id)
        if files is None:
            await query.answer("Нет прав или турнир не найден.", show_alert=True)
            return
        logging.getLogger(__name__).info(
            "[export_excel] t=%s → %d files: %s",
            tournament_id,
            len(files),
            [(fn, len(data)) for data, fn in files],
        )
        for data, filename in files:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=io.BytesIO(data),
                filename=filename,
            )
        _log("export_excel", user, tournament_id=tournament_id)
    finally:
        db.close()


async def callback_delete_tournament_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «🗑 Удалить турнир» — показывает запрос подтверждения."""
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
        result = _admin_handler(db).handle_delete_tournament_prompt(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_delete_tournament_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение удаления турнира."""
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
        result = _admin_handler(db).handle_delete_tournament_confirm(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("delete_tournament", user, tournament_id=tournament_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_delete_tournament_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена удаления — возвращает карточку турнира."""
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
        result = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_fill_opponents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «👥 Записать оппонентов» — показывает незаполненных оппонентов."""
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
        result = _admin_handler(db).handle_fill_opponents(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        if context.user_data is None:
            context.user_data = {}
        context.user_data[USER_DATA_OPPONENTS_MODE] = tournament_id
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_close_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «🔒 Закрыть турнир» в меню «• • •»."""
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
        result = _admin_handler(db).handle_close_tournament_by_id(user.id, tournament_id, allow_empty=settings.DEBUG)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("close_tournament", user, tournament_id=tournament_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_admin_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «• • •» — показывает скрытые admin-действия."""
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
            t = get_tournament(TournamentService(db).db, tournament_id)
            is_closed = t.status == TournamentStatus.CLOSED
            decks_hidden = t.decks_hidden
        except svc_errors.TournamentNotFound:
            is_closed = False
            decks_hidden = True
    finally:
        db.close()
    await query.edit_message_text(
        "Действия с турниром:",
        reply_markup=admin_more_keyboard(
            tournament_id, is_closed=is_closed, decks_hidden=decks_hidden, show_debug=settings.DEBUG
        ),
    )
    await query.answer()


async def callback_debug_round_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🐞 Debug: DM all round-opponent notifications for the tournament to the presser only.

    Lets an admin verify the whole notification path (build + format + delivery) without
    the scheduler and without messaging real players.
    """
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
        _log("debug_round_notify", user, tournament_id=tournament_id)
        sent = await send_debug_round_notifications(
            context.bot, db, tournament_id, user.id, datalens_service=DataLensService()
        )
    finally:
        db.close()

    if sent:
        await query.answer(f"Отправил тебе в ЛС {sent} твоих тест-уведомлений.", show_alert=True)
    else:
        await query.answer(
            "Нет твоих парингов в этом турнире (ты не участник или раунды ещё не импортированы).",
            show_alert=True,
        )


async def callback_reveal_decks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «👁 Показать колоды» — запрашивает подтверждение."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("reveal_decks_prompt", user, tournament_id=tournament_id)
    await query.edit_message_text(
        "Показать колоды всем участникам? Это действие нельзя отменить автоматически.",
        reply_markup=reveal_decks_confirm_keyboard(tournament_id),
    )
    await query.answer()


async def callback_reveal_decks_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение показа колод."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("reveal_decks_confirm", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_reveal_decks(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_reveal_decks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена показа колод — возврат к карточке турнира."""
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
        t = get_tournament(TournamentService(db).db, tournament_id)
        is_closed = t.status == TournamentStatus.CLOSED
        await query.edit_message_text(
            "Действия с турниром:",
            reply_markup=admin_more_keyboard(
                tournament_id, is_closed=is_closed, decks_hidden=t.decks_hidden, show_debug=settings.DEBUG
            ),
        )
    except svc_errors.TournamentNotFound:
        await query.answer("Турнир не найден.", show_alert=True)
    finally:
        db.close()
    await query.answer()


async def callback_hide_decks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «🙈 Скрыть колоды»."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("hide_decks", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_hide_decks(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    user = update.effective_user
    msg = update.effective_message
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_schedule(user.id, format_schedule_text())
    finally:
        db.close()
    await msg.reply_text(result.text)


async def callback_admin_player_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка ⋯ у участника — показывает меню действий."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, tournament_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_player_actions(user.id, participant_id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_admin_show_opponents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «👥 Показать оппонентов» — список оппонентов по пейрингам."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, tournament_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_player_opponents(user.id, participant_id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_admin_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «🗑 Удалить из турнира» — запрашивает подтверждение."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, tournament_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_remove_participant_confirm(user.id, participant_id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_admin_toggle_scorekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «🧙 Скорипер» — назначает или снимает роль скорипера у игрока."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, tournament_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_toggle_scorekeeper(user.id, participant_id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("admin_toggle_scorekeeper", user, participant_id=participant_id, tournament_id=tournament_id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer(result.answer_text or "", show_alert=bool(result.answer_text))
    finally:
        db.close()


async def callback_admin_remove_do(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение удаления участника — выполняет удаление."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    participant_id, tournament_id = ids
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_remove_participant(user.id, participant_id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("admin_remove_participant", user, participant_id=participant_id, tournament_id=tournament_id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()
