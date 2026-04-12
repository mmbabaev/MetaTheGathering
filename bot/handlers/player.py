# Регистрация, выбор колоды

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from services.tournament import TournamentService
from services import errors
from services.utils import get_tournament
from bot.handlers.base import HandlerResult
from bot.keyboards import (
    tournament_list_keyboard,
    register_button,
    archetype_keyboard,
    CB_REGISTER,
    CB_ARCHETYPE,
    CB_CUSTOM_ARCHETYPE,
    CB_TOURNAMENT,
)
from bot.messages import (
    NO_ACTIVE_TOURNAMENTS,
    CHOOSE_ARCHETYPE,
    CUSTOM_ARCHETYPE_PROMPT,
    REGISTERED_AS,
    REGISTERED,
    ALREADY_REGISTERED,
    REGISTRATION_CLOSED,
    TOURNAMENT_NOT_FOUND,
    NAME_REQUIRED_FOR_REGISTRATION,
    NAME_SAVED,
    format_tournament_card,
)

USER_DATA_PENDING_CUSTOM = "pending_custom_archetype_tournament_id"
USER_DATA_PENDING_NAME = "pending_name_for_tournament_id"


# --- Pure business logic functions ---

def handle_tournaments(db: Session) -> HandlerResult:
    svc = TournamentService(db)
    tournaments = svc.list_all_active_tournaments()
    if not tournaments:
        return HandlerResult(NO_ACTIVE_TOURNAMENTS)
    if len(tournaments) == 1:
        t = tournaments[0]
        text = format_tournament_card(t.title, t.status.label_ru, t.slug)
        return HandlerResult(text, keyboard=register_button(t.id))
    tour_list = [(t.id, t.title) for t in tournaments]
    return HandlerResult("Выберите турнир:", keyboard=tournament_list_keyboard(tour_list))


def handle_tournament_select(db: Session, tournament_id: int) -> HandlerResult:
    try:
        t = get_tournament(db, tournament_id)
    except errors.TournamentNotFound:
        return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
    text = format_tournament_card(t.title, t.status.label_ru, t.slug)
    return HandlerResult(text, keyboard=register_button(tournament_id))


def handle_register(db: Session, tournament_id: int, tg_id: int | None = None) -> HandlerResult:
    svc = TournamentService(db)
    if tg_id is not None:
        archetypes = svc.list_archetypes_for_user(tg_id)
    else:
        archetypes = svc.list_archetypes()[:10]
    arch_list = [(a.id, a.name) for a in archetypes]
    return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))


def user_needs_name(db: Session, tg_id: int) -> bool:
    """Возвращает True если у пользователя не задано имя в базе."""
    svc = TournamentService(db)
    user = svc.get_user_by_tg_id(tg_id)
    return user is None or not user.first_name


def handle_save_name_then_register(
    db: Session,
    tg_id: int,
    username: str | None,
    name_text: str,
    tournament_id: int,
) -> HandlerResult:
    """Сохраняет имя пользователя и возвращает выбор архетипа."""
    parts = name_text.strip().split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else None
    svc = TournamentService(db)
    svc.update_user_name(tg_id, first_name, last_name)
    archetypes = svc.list_archetypes_for_user(tg_id)
    arch_list = [(a.id, a.name) for a in archetypes]
    return HandlerResult(CHOOSE_ARCHETYPE, keyboard=archetype_keyboard(tournament_id, arch_list))


def handle_archetype(
    db: Session,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    tournament_id: int,
    archetype_id: int,
) -> HandlerResult:
    svc = TournamentService(db)
    try:
        db_user = svc.get_or_create_user(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        svc.register_participant(
            tournament_id=tournament_id,
            user_id=db_user.id,
            archetype_id=archetype_id,
        )
        archetypes = {a.id: a.name for a in svc.list_archetypes()}
        name = archetypes.get(archetype_id, "?")
        return HandlerResult(REGISTERED_AS.format(archetype_name=name))
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult(ALREADY_REGISTERED, is_alert=True)
    except errors.TournamentInvalidState:
        return HandlerResult(REGISTRATION_CLOSED, is_alert=True)


def handle_custom_archetype_text(
    db: Session,
    tg_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    tournament_id: int,
    name: str,
) -> HandlerResult:
    svc = TournamentService(db)
    try:
        archetype = svc.get_or_create_archetype_by_name(name)
        db_user = svc.get_or_create_user(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        svc.register_participant(
            tournament_id=tournament_id,
            user_id=db_user.id,
            archetype_id=archetype.id,
        )
        return HandlerResult(REGISTERED)
    except errors.ParticipantAlreadyRegistered:
        return HandlerResult(ALREADY_REGISTERED)
    except errors.TournamentInvalidState:
        return HandlerResult(REGISTRATION_CLOSED)


# --- Telegram wrappers ---

async def cmd_tournaments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    db = SessionLocal()
    try:
        result = handle_tournaments(db)
        await update.effective_message.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()


async def callback_tournament_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
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
        result = handle_tournament_select(db, tournament_id)
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
    if not user:
        await query.answer("Ошибка: не удалось определить пользователя.")
        return
    db = SessionLocal()
    try:
        if user_needs_name(db, user.id):
            if context.user_data is None:
                context.user_data = {}
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
            await query.edit_message_text(NAME_REQUIRED_FOR_REGISTRATION)
            await query.answer()
            return
        result = handle_register(db, tournament_id, tg_id=user.id)
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
        result = handle_archetype(
            db, user.id, user.username, user.first_name, user.last_name,
            tournament_id, archetype_id,
        )
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return
        await query.edit_message_text(result.text)
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


async def message_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единый обработчик текстовых сообщений для всех состояний user_data."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    if context.user_data is None:
        return

    text = msg.text.strip()

    # --- State: waiting for name to complete registration ---
    if USER_DATA_PENDING_NAME in context.user_data:
        tournament_id = context.user_data.pop(USER_DATA_PENDING_NAME)
        if not text:
            context.user_data[USER_DATA_PENDING_NAME] = tournament_id
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = handle_save_name_then_register(
                db, user.id, user.username, text, tournament_id,
            )
            await msg.reply_text(result.text, reply_markup=result.keyboard)
        finally:
            db.close()
        return

    # --- State: waiting for name change from /settings ---
    from bot.handlers.settings import USER_DATA_PENDING_SETTINGS_NAME, handle_settings_name_text
    if context.user_data.pop(USER_DATA_PENDING_SETTINGS_NAME, None):
        if not text:
            context.user_data[USER_DATA_PENDING_SETTINGS_NAME] = True
            await msg.reply_text("Введите непустое имя.")
            return
        db = SessionLocal()
        try:
            result = handle_settings_name_text(db, user.id, text)
            await msg.reply_text(result.text)
        finally:
            db.close()
        return

    # --- State: waiting for custom archetype name ---
    tournament_id = context.user_data.pop(USER_DATA_PENDING_CUSTOM, None)
    if tournament_id is None:
        return
    if not text:
        context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
        await msg.reply_text("Введите непустое название архетипа.")
        return
    db = SessionLocal()
    try:
        result = handle_custom_archetype_text(
            db, user.id, user.username, user.first_name, user.last_name,
            tournament_id, text,
        )
        await msg.reply_text(result.text)
    finally:
        db.close()


# Keep old name as alias so existing references don't break
message_custom_archetype = message_text_input
