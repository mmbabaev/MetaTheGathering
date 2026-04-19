# Telegram-обёртки для PlayerHandler

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from core.event_log import event_logger
from services.tournament import TournamentService
from services.user import UserService
from bot.handlers.player import PlayerHandler
from bot.handlers.settings import SettingsHandler
from bot.keyboards import CB_REGISTER, CB_ARCHETYPE, CB_CUSTOM_ARCHETYPE, CB_TOURNAMENT, CB_ARCHETYPE_MORE
from bot.messages import CUSTOM_ARCHETYPE_PROMPT
from bot.handlers.admin import AdminHandler


def _log(event: str, user, **params) -> None:
    event_logger.log(
        event,
        tg_id=user.id if user else None,
        username=user.username if user else None,
        **params,
    )

USER_DATA_PENDING_CUSTOM = "pending_custom_archetype_tournament_id"
USER_DATA_PENDING_NAME = "pending_name_for_tournament_id"
USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"
USER_DATA_PENDING_BULK_ADD = "pending_bulk_add_tournament_id"
USER_DATA_PENDING_ADMIN_CUSTOM_ARCH = "pending_admin_custom_arch_participant_id"


def _player_handler(db) -> PlayerHandler:
    return PlayerHandler(TournamentService(db), UserService(db))

def _settings_handler(db) -> SettingsHandler:
    return SettingsHandler(UserService(db))

def _admin_handler(db) -> AdminHandler:
    return AdminHandler(TournamentService(db), UserService(db))


async def cmd_tournaments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    user = update.effective_user
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_tournaments(tg_id=user.id if user else None)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_tournament_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id if user else None)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_register(tournament_id, tg_id=user.id if user else None)
        if result.needs_name:
            if context.user_data is None:
                context.user_data = {}
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str, aid_str = query.data.split(":", 2)
        tournament_id = int(tid_str)
        archetype_id = int(aid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_archetype(
            user.id, None, None, None,
            tournament_id, archetype_id,
        )
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("register", user, tournament_id=tournament_id, archetype_id=archetype_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_archetype_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_archetype_more(tournament_id, tg_id=user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_custom_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
    await query.edit_message_text(CUSTOM_ARCHETYPE_PROMPT)
    await query.answer()


async def callback_tournament_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        admin_h = _admin_handler(db)
        if user and admin_h.user_svc.is_admin(user.id):
            result = admin_h.handle_admin_status(user.id, tournament_id)
        else:
            result = _player_handler(db).handle_tournament_public_status(tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_leave_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_leave_tournament(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_leave_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_leave_confirm(user.id, tournament_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("leave", user, tournament_id=tournament_id)
        await query.edit_message_text(result.text)
        await query.answer()
    finally:
        db.close()


async def callback_leave_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    try:
        _, tid_str = query.data.split(":", 1)
        tournament_id = int(tid_str)
    except (ValueError, IndexError):
        await query.answer("Ошибка данных.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def message_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    if context.user_data is None:
        return

    text = msg.text.strip()

    if USER_DATA_PENDING_NAME in context.user_data:
        tournament_id = context.user_data.pop(USER_DATA_PENDING_NAME)
        if not text:
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = _player_handler(db).handle_save_name_then_register(
                user.id, user.username, text, tournament_id,
            )
            await msg.reply_text(result.text, reply_markup=result.keyboard)
        finally:
            db.close()
        return

    if context.user_data.pop(USER_DATA_PENDING_SETTINGS_NAME, None):
        if not text:
            context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = _settings_handler(db).handle_settings_name_text(user.id, text)
            await msg.reply_text(result.text)
        finally:
            db.close()
        return

    if USER_DATA_PENDING_ADMIN_CUSTOM_ARCH in context.user_data:
        participant_id = context.user_data.pop(USER_DATA_PENDING_ADMIN_CUSTOM_ARCH)
        if not text:
            context.user_data[USER_DATA_PENDING_ADMIN_CUSTOM_ARCH] = participant_id
            await msg.reply_text("Введите непустое название архетипа.")
            return
        db = SessionLocal()
        try:
            result = _admin_handler(db).handle_admin_custom_arch_text(user.id, participant_id, text)
            if not result.is_alert:
                _log("admin_custom_arch", user, participant_id=participant_id, arch_name=text)
            await msg.reply_text(result.text)
        finally:
            db.close()
        return

    if USER_DATA_PENDING_BULK_ADD in context.user_data:
        tournament_id = context.user_data.pop(USER_DATA_PENDING_BULK_ADD)
        names = [line.strip() for line in text.splitlines() if line.strip()]
        db = SessionLocal()
        try:
            result = _admin_handler(db).handle_bulk_add_by_name(user.id, tournament_id, names)
            _log("bulk_add", user, tournament_id=tournament_id, names=names)
            await msg.reply_text(result.text, reply_markup=result.keyboard)
        finally:
            db.close()
        return

    tournament_id = context.user_data.pop(USER_DATA_PENDING_CUSTOM, None)
    if tournament_id is None:
        return
    if not text:
        context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
        await msg.reply_text("Введите непустое название архетипа.")
        return
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_custom_archetype_text(
            user.id, None, None, None,
            tournament_id, text,
        )
        await msg.reply_text(result.text)
    finally:
        db.close()
