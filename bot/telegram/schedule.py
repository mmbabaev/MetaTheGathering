"""Telegram-обёртки для расписания клубов (issue #124/#125)."""

from telegram import Message, Update, User
from telegram.ext import ContextTypes

from bot.handlers.schedule import ScheduleHandler
from bot.keyboards import Keyboards
from bot.telegram.common import log_event as _log
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services.schedule import ScheduleService
from services.user import UserService

# pending-ввод времени/импортов: (row_id, kind) где kind = create/game/reminder/imports
USER_DATA_PENDING_SCHEDULE_EDIT = "pending_schedule_edit"


def _schedule_handler(db) -> ScheduleHandler:
    return ScheduleHandler(ScheduleService(db), UserService(db), Keyboards())


def _reload_jobs(context, user, row_id: int) -> str:
    """Перевешивает джобы расписания после правки. Возвращает текст для query.answer."""
    from bot.scheduler import reload_schedule_jobs  # noqa: PLC0415 — иначе цикл импортов

    try:
        reload_schedule_jobs(context.application)
        return "Применено сразу."
    except Exception:
        _log("schedule_reload_failed", user, row_id=row_id)
        return "⚠️ Сохранено, применится после рестарта бота."


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/schedule — расписание + кнопки на каждую строку."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    _log("cmd_schedule", user)
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_list(user.id)
    finally:
        db.close()
    await msg.reply_text(result.text, reply_markup=result.keyboard)


async def callback_schedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«⬅️ Назад» из карточки — снова список строк."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_list(user.id)
    finally:
        db.close()
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_schedule_row(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тап по строке расписания — карточка."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_schedule_row(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_schedule_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Тумблер строки — правим БД и СРАЗУ перевешиваем джобы, без перезапуска бота."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_toggle_row(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    applied = _reload_jobs(context, user, row_id)
    _log("schedule_toggle", user, row_id=row_id)
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer(applied)


async def callback_schedule_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка времени (создание/игра/напоминание) — просит прислать значение текстом."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    row_id, field_idx = ids
    db = SessionLocal()
    try:
        handler = _schedule_handler(db)
        field = handler.field_name(field_idx)
        if field is None:
            await query.answer("Ошибка данных.", show_alert=True)
            return
        result = handler.handle_edit_field_prompt(user.id, row_id, field)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SCHEDULE_EDIT] = (row_id, field)
    await query.answer()
    await query.message.reply_text(result.text)


async def callback_schedule_imports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка импортов — просит прислать пресет «начало-конец/шаг» текстом."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_imports_prompt(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    if context.user_data is None:
        context.user_data = {}
    context.user_data[USER_DATA_PENDING_SCHEDULE_EDIT] = (row_id, "imports")
    await query.answer()
    await query.message.reply_text(result.text)


async def callback_schedule_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопка «День» — показывает пикер дня недели."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 1)
    if ids is None:
        return
    (row_id,) = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_weekday_picker(user.id, row_id)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer()


async def callback_schedule_set_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выбор дня недели в пикере — применяет и перевешивает джобы."""
    query = update.callback_query
    user = update.effective_user
    if not user:
        return
    ids = await parse_callback_ints(query, 2)
    if ids is None:
        return
    row_id, weekday_idx = ids
    db = SessionLocal()
    try:
        result = _schedule_handler(db).handle_set_weekday(user.id, row_id, weekday_idx)
    finally:
        db.close()
    if result.is_alert:
        await query.answer(result.text, show_alert=True)
        return
    applied = _reload_jobs(context, user, row_id)
    _log("schedule_set_weekday", user, row_id=row_id, weekday_idx=weekday_idx)
    await query.edit_message_text(result.text, reply_markup=result.keyboard)
    await query.answer(applied)


async def handle_pending_schedule_edit(msg: Message, user: User, text: str, context) -> bool:
    """Обрабатывает ввод времени/импортов для расписания. True если обработал."""
    pending = context.user_data.get(USER_DATA_PENDING_SCHEDULE_EDIT)
    if pending is None:
        return False
    row_id, kind = pending
    context.user_data.pop(USER_DATA_PENDING_SCHEDULE_EDIT)

    db = SessionLocal()
    try:
        handler = _schedule_handler(db)
        if kind == "imports":
            result = handler.handle_set_imports(user.id, row_id, text)
        else:
            result = handler.handle_set_time(user.id, row_id, kind, text)
    finally:
        db.close()

    if result.is_alert:
        await msg.reply_text(result.text)
        return True
    # result без клавиатуры = ошибка формата (BAD_TIME/BAD_IMPORTS): не применяли, не перевешиваем
    if result.keyboard is None:
        await msg.reply_text(result.text)
        return True

    from bot.scheduler import reload_schedule_jobs  # noqa: PLC0415 — иначе цикл импортов

    try:
        reload_schedule_jobs(context.application)
    except Exception:
        _log("schedule_reload_failed", user, row_id=row_id)
    _log("schedule_edit", user, row_id=row_id, kind=kind)
    await msg.reply_text(result.text, reply_markup=result.keyboard)
    return True
