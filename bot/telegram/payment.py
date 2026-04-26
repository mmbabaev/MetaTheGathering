from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.payment import PaymentHandler
from bot.keyboards import Keyboards
from bot.telegram.common import parse_callback_ints
from core.database import SessionLocal
from services import errors
from services.payment_service import PaymentService
from services.user import UserService
from services.utils import get_tournament


def _payment_handler(db) -> PaymentHandler:
    return PaymentHandler(PaymentService(db), UserService(db), Keyboards())


async def callback_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        try:
            t = get_tournament(db, tournament_id)
        except errors.TournamentNotFound:
            await query.answer("Турнир не найден.", show_alert=True)
            return

        result = _payment_handler(db).handle_pay(user.id, tournament_id, t.title)
        if result.is_alert:
            await query.answer(result.text, show_alert=True)
            return

        await query.answer()
        sent = await query.message.reply_text(result.text, reply_markup=result.keyboard)

        # Сохраняем chat_id + message_id чтобы webhook мог обновить сообщение
        if result.yookassa_id:
            PaymentService(db).set_message_info(
                yookassa_id=result.yookassa_id,
                tg_chat_id=sent.chat_id,
                tg_message_id=sent.message_id,
            )
    finally:
        db.close()
