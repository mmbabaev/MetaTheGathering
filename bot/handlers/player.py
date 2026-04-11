# Регистрация, выбор колоды

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from core.models import TournamentStatus
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
    format_tournament_card,
)

USER_DATA_PENDING_CUSTOM = "pending_custom_archetype_tournament_id"


def _status_display(status: TournamentStatus) -> str:
    return {
        TournamentStatus.REGISTRATION: "Регистрация",
        TournamentStatus.ONGOING: "Идёт",
        TournamentStatus.VOTING: "Голосование",
        TournamentStatus.CLOSED: "Завершён",
    }.get(status, status.value)


# --- Pure business logic functions ---

def handle_tournaments(db: Session) -> HandlerResult:
    svc = TournamentService(db)
    tournaments = svc.list_all_active_tournaments()
    if not tournaments:
        return HandlerResult(NO_ACTIVE_TOURNAMENTS)
    if len(tournaments) == 1:
        t = tournaments[0]
        text = format_tournament_card(t.title, _status_display(t.status), t.slug)
        return HandlerResult(text, keyboard=register_button(t.id))
    tour_list = [(t.id, t.title) for t in tournaments]
    return HandlerResult("Выберите турнир:", keyboard=tournament_list_keyboard(tour_list))


def handle_tournament_select(db: Session, tournament_id: int) -> HandlerResult:
    try:
        t = get_tournament(db, tournament_id)
    except errors.TournamentNotFound:
        return HandlerResult(TOURNAMENT_NOT_FOUND, is_alert=True)
    text = format_tournament_card(t.title, _status_display(t.status), t.slug)
    return HandlerResult(text, keyboard=register_button(tournament_id))


def handle_register(db: Session, tournament_id: int) -> HandlerResult:
    svc = TournamentService(db)
    archetypes = svc.list_archetypes()
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
        result = handle_register(db, tournament_id)
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


async def message_custom_archetype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.text:
        return
    if context.user_data is None:
        return
    tournament_id = context.user_data.pop(USER_DATA_PENDING_CUSTOM, None)
    if tournament_id is None:
        return
    user = update.effective_user
    if not user:
        return
    name = update.effective_message.text.strip()
    if not name:
        context.user_data[USER_DATA_PENDING_CUSTOM] = tournament_id
        await update.effective_message.reply_text("Введите непустое название архетипа.")
        return
    db = SessionLocal()
    try:
        result = handle_custom_archetype_text(
            db, user.id, user.username, user.first_name, user.last_name,
            tournament_id, name,
        )
        await update.effective_message.reply_text(result.text)
    finally:
        db.close()
