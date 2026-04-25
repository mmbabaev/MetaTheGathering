# Telegram-обёртки для admin-хендлеров

import io

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.handlers.admin import AdminHandler, parse_add_player_command, parse_bulk_player_line
from bot.handlers.player import PlayerHandler
from bot.keyboards import admin_more_keyboard
from bot.messages import ADD_PLAYERS_USAGE, BULK_ADD_PROMPT, TELEGRAM_USER_LOOKUP_FAILED
from bot.scheduler import format_schedule_text
from bot.telegram.common import log_event as _log
from bot.telegram.common import parse_callback_ints
from bot.telegram.player import (
    USER_DATA_OPPONENTS_MODE,
    USER_DATA_PENDING_ADMIN_CUSTOM_ARCH,
    USER_DATA_PENDING_BULK_ADD,
    _make_features,
    _make_keyboards,
)
from core.config import app_cfg, settings
from core.database import SessionLocal
from core.models import TournamentStatus
from services import errors as svc_errors
from services.aetherhub_import_service import AetherhubImportService
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from services.user import UserService
from services.utils import get_tournament


def _admin_handler(db) -> AdminHandler:
    return AdminHandler(
        TournamentService(db), UserService(db), ArchetypeService(db), _make_keyboards(), _make_features()
    )


def _player_handler(db) -> PlayerHandler:
    return PlayerHandler(TournamentService(db), UserService(db), ArchetypeService(db), _make_keyboards())


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


async def callback_admin_pick_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _admin_handler(db).handle_admin_pick_arch(user.id, participant_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_admin_set_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _admin_handler(db).handle_admin_set_arch(user.id, participant_id, archetype_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("admin_set_arch", user, participant_id=participant_id, archetype_id=archetype_id)

        opponents_tournament_id = (context.user_data or {}).get(USER_DATA_OPPONENTS_MODE)
        if opponents_tournament_id is not None:
            await query.edit_message_text(result.text)
            await query.answer()
            opponents_result = _admin_handler(db).handle_admin_opponents(user.id, opponents_tournament_id)
            if opponents_result.is_alert:
                context.user_data.pop(USER_DATA_OPPONENTS_MODE, None)
                has_pairings = bool(AetherhubImportService(db).get_pairings(opponents_tournament_id))
                card = _player_handler(db).handle_tournament_select(
                    opponents_tournament_id, tg_id=user.id, has_pairings=has_pairings
                )
                await query.message.reply_text(card.text, reply_markup=card.keyboard)
            else:
                await query.message.reply_text(opponents_result.text, reply_markup=opponents_result.keyboard)
        else:
            await query.edit_message_text(result.text, reply_markup=result.keyboard)
            await query.answer()
    finally:
        db.close()


async def callback_admin_arch_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _admin_handler(db).handle_admin_arch_more(user.id, participant_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_admin_custom_arch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


async def cmd_add_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add_me <deck_name> — регистрирует администратора в текущем турнире."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    deck_name = " ".join(context.args or []).strip()
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_add_me(user.id, user.username, user.first_name, user.last_name, deck_name)
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
            await msg.reply_text(f"❌ @{username} — укажите @username человека (не группу или канал).")
            return
        target_tg_id = chat.id
        target_first_name = chat.first_name
        target_last_name = chat.last_name
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_add_player(
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


async def callback_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «📊 Выгрузка Excel» — отправляет файл участников."""
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
        result = _admin_handler(db).handle_export_excel(user.id, tournament_id)
        if result is None:
            await query.answer("Нет прав или турнир не найден.", show_alert=True)
            return
        data, filename = result
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


async def callback_admin_opponents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _admin_handler(db).handle_admin_opponents(user.id, tournament_id)
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
        except svc_errors.TournamentNotFound:
            is_closed = False
    finally:
        db.close()
    await query.edit_message_text(
        "Действия с турниром:", reply_markup=admin_more_keyboard(tournament_id, is_closed=is_closed)
    )
    await query.answer()


async def callback_reveal_decks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «👁 Показать колоды» — снимает скрытие колод для всех."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("reveal_decks", user, tournament_id=tournament_id)
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
