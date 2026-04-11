# Регистрация, выбор колоды

from telegram import Update
from telegram.ext import ContextTypes

from core.database import SessionLocal
from core.models import TournamentStatus
from services.tournament import TournamentService
from services import errors
from services.utils import get_tournament
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


async def cmd_tournaments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    db = SessionLocal()
    try:
        svc = TournamentService(db)
        tournaments = svc.list_active_tournaments_for_chat(chat_id)
        if not tournaments:
            await update.effective_message.reply_text(NO_ACTIVE_TOURNAMENTS)
            return
        if len(tournaments) == 1:
            t = tournaments[0]
            text = format_tournament_card(
                t.title, _status_display(t.status), t.slug
            )
            await update.effective_message.reply_text(
                text,
                reply_markup=register_button(t.id),
            )
            return
        # Несколько турниров — список кнопок
        tour_list = [(t.id, t.title) for t in tournaments]
        await update.effective_message.reply_text(
            "Выберите турнир:",
            reply_markup=tournament_list_keyboard(tour_list),
        )
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
        svc = TournamentService(db)
        try:
            t = get_tournament(db, tournament_id)
        except errors.TournamentNotFound:
            await query.answer(TOURNAMENT_NOT_FOUND, show_alert=True)
            return
        text = format_tournament_card(
            t.title, _status_display(t.status), t.slug
        )
        await query.edit_message_text(
            text,
            reply_markup=register_button(tournament_id),
        )
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
        svc = TournamentService(db)
        archetypes = svc.list_archetypes()
        arch_list = [(a.id, a.name) for a in archetypes]
        await query.edit_message_text(
            CHOOSE_ARCHETYPE,
            reply_markup=archetype_keyboard(tournament_id, arch_list),
        )
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
        svc = TournamentService(db)
        try:
            db_user = svc.get_or_create_user(
                tg_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            participant = svc.register_participant(
                tournament_id=tournament_id,
                user_id=db_user.id,
                archetype_id=archetype_id,
            )
            archetypes = {a.id: a.name for a in svc.list_archetypes()}
            name = archetypes.get(archetype_id, "?")
            await query.edit_message_text(REGISTERED_AS.format(archetype_name=name))
        except errors.ParticipantAlreadyRegistered:
            await query.answer(ALREADY_REGISTERED, show_alert=True)
            return
        except errors.TournamentInvalidState:
            await query.answer(REGISTRATION_CLOSED, show_alert=True)
            return
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
        svc = TournamentService(db)
        try:
            archetype = svc.get_or_create_archetype_by_name(name)
            db_user = svc.get_or_create_user(
                tg_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            svc.register_participant(
                tournament_id=tournament_id,
                user_id=db_user.id,
                archetype_id=archetype.id,
            )
            await update.effective_message.reply_text(REGISTERED)
        except errors.ParticipantAlreadyRegistered:
            await update.effective_message.reply_text(ALREADY_REGISTERED)
        except errors.TournamentInvalidState:
            await update.effective_message.reply_text(REGISTRATION_CLOSED)
    finally:
        db.close()
