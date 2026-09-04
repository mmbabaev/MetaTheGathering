# Telegram-обёртки для PlayerHandler

from telegram import Update
from telegram.ext import ContextTypes

from bot.features import FeatureService
from bot.handlers.admin import AdminHandler
from bot.handlers.base import HandlerResult
from bot.handlers.cellar import CellarHandler
from bot.handlers.player import PlayerHandler
from bot.handlers.settings import SettingsHandler
from bot.keyboards import Keyboards
from bot.messages import CUSTOM_ARCHETYPE_PROMPT
from bot.meta_police_message import refresh_meta_police_message
from bot.telegram.common import announce_completion_if_ready, parse_callback_ints
from bot.telegram.common import log_event as _log
from core.database import SessionLocal
from services.aetherhub_import_service import AetherhubImportService
from services.archetype import ArchetypeService
from services.feature_flags import FeatureFlagService
from services.payment_service import PaymentService
from services.tournament import TournamentService
from services.user import UserService

USER_DATA_PENDING_CUSTOM = "pending_custom_archetype_tournament_id"
USER_DATA_PENDING_NAME = "pending_name_for_tournament_id"
USER_DATA_PENDING_ENDSTEP_USERNAME = "pending_endstep_username_for_tournament_id"
USER_DATA_PENDING_SETTINGS_NAME = "pending_settings_name"
USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME = "pending_settings_endstep_username"
USER_DATA_PENDING_CELLAR_NAME = "pending_cellar_name"
USER_DATA_PENDING_BULK_ADD = "pending_bulk_add_tournament_id"
USER_DATA_PENDING_ADMIN_CUSTOM_ARCH = "pending_admin_custom_arch_participant_id"
USER_DATA_OPPONENTS_MODE = "opponents_tournament_id"
USER_DATA_PENDING_META_IMPORT = "pending_meta_import_tournament_id"
USER_DATA_PENDING_MISSING_CUSTOM_ARCH = "pending_missing_custom_arch_participant_id"


def _make_features(db) -> FeatureService:
    return FeatureService(FeatureFlagService(db))


def _player_handler(db) -> PlayerHandler:
    return PlayerHandler(
        TournamentService(db),
        UserService(db),
        ArchetypeService(db),
        Keyboards(),
        AetherhubImportService(db),
        _make_features(db),
        PaymentService(db),
    )


def _set_registration_pending(context, result: HandlerResult, tournament_id: int) -> None:
    if context.user_data is None:
        context.user_data = {}
    if result.needs_name:
        context.user_data[USER_DATA_PENDING_NAME] = tournament_id
        context.user_data.pop(USER_DATA_PENDING_ENDSTEP_USERNAME, None)
    elif result.needs_endstep_username:
        context.user_data[USER_DATA_PENDING_ENDSTEP_USERNAME] = tournament_id
        context.user_data.pop(USER_DATA_PENDING_NAME, None)


def _settings_handler(db) -> SettingsHandler:
    return SettingsHandler(UserService(db))


def _admin_handler(db) -> AdminHandler:
    return AdminHandler(TournamentService(db), UserService(db), ArchetypeService(db), Keyboards(), _make_features(db))


async def cmd_tournaments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    user = update.effective_user
    _log("cmd_tournaments", user)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_tournaments(tg_id=user.id if user else None)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_tournament_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("view_tournament", user, tournament_id=tournament_id)
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
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("register_start", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_register(tournament_id, tg_id=user.id if user else None)
        _set_registration_pending(context, result, tournament_id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    tournament_id, archetype_id = ids
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_archetype(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            tournament_id,
            archetype_id,
        )
        if result.needs_name or result.needs_endstep_username:
            _set_registration_pending(context, result, tournament_id)
            await query.edit_message_text(result.text, reply_markup=result.keyboard)
            await query.answer()
            return
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("register", user, tournament_id=tournament_id, archetype_id=archetype_id)
        await query.edit_message_text(result.text)
        await query.answer()
        card = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
        await query.message.reply_text(card.text, reply_markup=card.keyboard)
        await refresh_meta_police_message(context.bot, db, tournament_id)
        await announce_completion_if_ready(context.bot, db, tournament_id)
    finally:
        db.close()


async def callback_defer_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _player_handler(db).handle_defer_deck(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            tournament_id,
        )
        if result.needs_name or result.needs_endstep_username:
            _set_registration_pending(context, result, tournament_id)
            await query.edit_message_text(result.text, reply_markup=result.keyboard)
            await query.answer()
            return
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log("register_deck_later", user, tournament_id=tournament_id)
        await query.edit_message_text(result.text)
        await query.answer()
        card = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
        await query.message.reply_text(card.text, reply_markup=card.keyboard)
    finally:
        db.close()


async def callback_archetype_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _player_handler(db).handle_archetype_more(tournament_id, tg_id=user.id)
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_custom_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
    await query.edit_message_text(CUSTOM_ARCHETYPE_PROMPT)
    await query.answer()


async def callback_pick_missing_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _player_handler(db).handle_pick_missing_deck(user.id, participant_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_missing_deck_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        result = _player_handler(db).handle_pick_missing_deck(user.id, participant_id, expanded=True)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
    finally:
        db.close()


async def callback_set_missing_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        participant = TournamentService(db).get_participant_by_id(participant_id)
        target = UserService(db).get_by_id(participant.user_id) if participant else None
        result = _player_handler(db).handle_set_missing_deck(user.id, participant_id, archetype_id)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        _log(
            "meta_police_deck_recorded",
            user,
            tournament_id=participant.tournament_id if participant else None,
            participant_id=participant_id,
            target_tg_id=target.tg_id if target else None,
            archetype_id=archetype_id,
        )
        await query.edit_message_text(result.text, reply_markup=result.keyboard)
        await query.answer()
        await refresh_meta_police_message(
            context.bot,
            db,
            participant.tournament_id if participant else None,
        )
        await announce_completion_if_ready(
            context.bot,
            db,
            participant.tournament_id if participant else None,
        )
    finally:
        db.close()


async def callback_missing_custom_deck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        validation = _player_handler(db).handle_pick_missing_deck(user.id, participant_id)
        if validation.is_alert:
            await query.answer(validation.text, show_alert=True)
            return
        if context.user_data is None:
            context.user_data = {}
        context.user_data[USER_DATA_PENDING_MISSING_CUSTOM_ARCH] = participant_id
        await query.edit_message_text(CUSTOM_ARCHETYPE_PROMPT)
        await query.answer()
    finally:
        db.close()


async def callback_tournament_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("view_status", user, tournament_id=tournament_id)
    db = SessionLocal()
    try:
        admin_h = _admin_handler(db)
        if user and admin_h.user_svc.is_privileged(user.id):
            result = admin_h.handle_admin_status(user.id, tournament_id)
        else:
            result = _player_handler(db).handle_tournament_public_status(tournament_id, tg_id=user.id if user else None)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text, reply_markup=result.keyboard, parse_mode=result.parse_mode)
        await query.answer()
    finally:
        db.close()


async def callback_leave_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
    _log("leave_start", user, tournament_id=tournament_id)
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
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
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
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (tournament_id,) = ids
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


async def _handle_pending_name(msg, user, text, context) -> bool:
    tournament_id = context.user_data.get(USER_DATA_PENDING_NAME)
    if tournament_id is None:
        return False
    if not text:
        await msg.reply_text("Введите непустое имя.")
        return True
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_save_name_then_register(
            user.id,
            user.username,
            text,
            tournament_id,
        )
        if not result.needs_name:
            context.user_data.pop(USER_DATA_PENDING_NAME, None)
        if result.needs_endstep_username:
            _set_registration_pending(context, result, tournament_id)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    return True


async def _handle_pending_endstep_username(msg, user, text, context) -> bool:
    tournament_id = context.user_data.get(USER_DATA_PENDING_ENDSTEP_USERNAME)
    if tournament_id is None:
        return False
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_save_endstep_username_then_register(user.id, text, tournament_id)
        if result.needs_name or result.needs_endstep_username:
            _set_registration_pending(context, result, tournament_id)
        else:
            context.user_data.pop(USER_DATA_PENDING_ENDSTEP_USERNAME, None)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    return True


async def _handle_pending_settings_name(msg, user, text, context) -> bool:
    if not context.user_data.get(USER_DATA_PENDING_SETTINGS_NAME):
        return False
    if not text:
        await msg.reply_text("Введите непустое имя.")
        return True
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_settings_name_text(user.id, text)
        if not result.needs_name:
            context.user_data.pop(USER_DATA_PENDING_SETTINGS_NAME, None)
        await msg.reply_text(result.text)
    finally:
        db.close()
    return True


async def _handle_pending_settings_endstep_username(msg, user, text, context) -> bool:
    if not context.user_data.get(USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME):
        return False
    db = SessionLocal()
    try:
        result = _settings_handler(db).handle_settings_endstep_username_text(user.id, text)
        if not result.needs_endstep_username:
            context.user_data.pop(USER_DATA_PENDING_SETTINGS_ENDSTEP_USERNAME, None)
        await msg.reply_text(result.text)
    finally:
        db.close()
    return True


async def _handle_pending_cellar_name(msg, user, text, context) -> bool:
    if not context.user_data.get(USER_DATA_PENDING_CELLAR_NAME):
        return False
    if not text:
        await msg.reply_text("Введите непустое имя.")
        return True
    db = SessionLocal()
    try:
        saved = _settings_handler(db).handle_settings_name_text(user.id, text)
        if saved.needs_name:
            await msg.reply_text(saved.text)
            return True
        context.user_data.pop(USER_DATA_PENDING_CELLAR_NAME, None)
        result = CellarHandler(db, UserService(db), FeatureFlagService(db)).handle_open(
            tg_id=user.id,
            username=user.username,
            first_name=None,
            last_name=None,
        )
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    return True


async def _handle_pending_admin_custom_arch(msg, user, text, context) -> bool:
    participant_id = context.user_data.get(USER_DATA_PENDING_ADMIN_CUSTOM_ARCH)
    if participant_id is None:
        return False
    if not text:
        await msg.reply_text("Введите непустое название архетипа.")
        return True
    context.user_data.pop(USER_DATA_PENDING_ADMIN_CUSTOM_ARCH)
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_set_participant_custom_arch(user.id, participant_id, text)
        if not result.is_alert:
            _log("admin_custom_arch", user, participant_id=participant_id, arch_name=text)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
        if not result.is_alert:
            part = TournamentService(db).get_participant_by_id(participant_id)
            await refresh_meta_police_message(context.bot, db, part.tournament_id if part else None)
            await announce_completion_if_ready(context.bot, db, part.tournament_id if part else None)
    finally:
        db.close()
    return True


async def _handle_pending_missing_custom_arch(msg, user, text, context) -> bool:
    participant_id = context.user_data.get(USER_DATA_PENDING_MISSING_CUSTOM_ARCH)
    if participant_id is None:
        return False
    if not text:
        await msg.reply_text("Введите непустое название архетипа.")
        return True
    context.user_data.pop(USER_DATA_PENDING_MISSING_CUSTOM_ARCH)
    db = SessionLocal()
    try:
        participant = TournamentService(db).get_participant_by_id(participant_id)
        target = UserService(db).get_by_id(participant.user_id) if participant else None
        result = _player_handler(db).handle_set_missing_custom_deck(user.id, participant_id, text)
        if not result.is_alert:
            _log(
                "meta_police_deck_recorded",
                user,
                tournament_id=participant.tournament_id if participant else None,
                participant_id=participant_id,
                target_tg_id=target.tg_id if target else None,
                custom_archetype=text,
            )
        await msg.reply_text(result.text, reply_markup=result.keyboard)
        if not result.is_alert:
            await refresh_meta_police_message(
                context.bot,
                db,
                participant.tournament_id if participant else None,
            )
            await announce_completion_if_ready(
                context.bot,
                db,
                participant.tournament_id if participant else None,
            )
    finally:
        db.close()
    return True


async def _handle_pending_bulk_add(msg, user, text, context) -> bool:
    tournament_id = context.user_data.get(USER_DATA_PENDING_BULK_ADD)
    if tournament_id is None:
        return False
    context.user_data.pop(USER_DATA_PENDING_BULK_ADD)
    names = [line.strip() for line in text.splitlines() if line.strip()]
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_bulk_add_by_name(user.id, tournament_id, names)
        _log("bulk_add", user, tournament_id=tournament_id, names=names)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
    return True


async def _handle_pending_custom_arch(msg, user, text, context) -> bool:
    tournament_id = context.user_data.get(USER_DATA_PENDING_CUSTOM)
    if tournament_id is None:
        return False
    if not text:
        await msg.reply_text("Введите непустое название архетипа.")
        return True
    context.user_data.pop(USER_DATA_PENDING_CUSTOM)
    db = SessionLocal()
    try:
        result = _player_handler(db).handle_custom_archetype_text(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            tournament_id,
            text,
        )
        if result.needs_name or result.needs_endstep_username:
            _set_registration_pending(context, result, tournament_id)
            await msg.reply_text(result.text, reply_markup=result.keyboard)
        else:
            await msg.reply_text(result.text)
        if not result.is_alert and not result.needs_name and not result.needs_endstep_username:
            card = _player_handler(db).handle_tournament_select(tournament_id, tg_id=user.id)
            await msg.reply_text(card.text, reply_markup=card.keyboard)
            await refresh_meta_police_message(context.bot, db, tournament_id)
            await announce_completion_if_ready(context.bot, db, tournament_id)
    finally:
        db.close()
    return True


from bot.telegram.aetherhub import handle_pending_aetherhub_url as _handle_pending_aetherhub_url
from bot.telegram.aetherhub import handle_pending_import_time as _handle_pending_import_time
from bot.telegram.poll import handle_pending_link_poll as _handle_pending_link_poll
from bot.telegram.schedule import handle_pending_schedule_edit as _handle_pending_schedule_edit


async def _handle_pending_meta_import(msg, user, text, context) -> bool:
    tournament_id = context.user_data.get(USER_DATA_PENDING_META_IMPORT)
    if tournament_id is None:
        return False
    context.user_data.pop(USER_DATA_PENDING_META_IMPORT)
    db = SessionLocal()
    try:
        result = _admin_handler(db).handle_meta_import_table(user.id, tournament_id, text)
        if result.is_alert:
            await msg.reply_text(result.text)
            return True
        _log("meta_import_table", user, tournament_id=tournament_id)
        await msg.reply_text(result.text, reply_markup=result.keyboard, parse_mode=result.parse_mode)
        await refresh_meta_police_message(context.bot, db, tournament_id)
        await announce_completion_if_ready(context.bot, db, tournament_id)
    finally:
        db.close()
    return True


_TEXT_INPUT_HANDLERS = [
    _handle_pending_name,
    _handle_pending_endstep_username,
    _handle_pending_cellar_name,
    _handle_pending_settings_name,
    _handle_pending_settings_endstep_username,
    _handle_pending_missing_custom_arch,
    _handle_pending_admin_custom_arch,
    _handle_pending_bulk_add,
    _handle_pending_custom_arch,
    _handle_pending_link_poll,
    _handle_pending_aetherhub_url,
    _handle_pending_import_time,
    _handle_pending_meta_import,
    _handle_pending_schedule_edit,
]


async def message_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    if not context.user_data:
        return

    text = msg.text.strip()
    for handler in _TEXT_INPUT_HANDLERS:
        if await handler(msg, user, text, context):
            return
