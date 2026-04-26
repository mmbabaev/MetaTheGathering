import logging

from bot.handlers.base import HandlerResult
from bot.keyboards import Keyboards
from core.config import settings
from services.payment_service import PaymentService
from services.user import UserService

logger = logging.getLogger(__name__)

PAYMENT_ERROR = "Ошибка при создании платежа. Попробуйте позже."
PAYMENT_NOT_CONFIGURED = "Оплата через бота пока не настроена. Обратитесь к организатору."


class PaymentHandler:
    def __init__(self, payment_svc: PaymentService, user_svc: UserService, keyboards: Keyboards) -> None:
        self.payment_svc = payment_svc
        self.user_svc = user_svc
        self.keyboards = keyboards

    def handle_pay(self, tg_id: int, tournament_id: int, tournament_title: str) -> HandlerResult:
        if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
            return HandlerResult(PAYMENT_NOT_CONFIGURED, is_alert=True)

        user = self.user_svc.get_by_tg_id(tg_id)
        name = ""
        if user:
            parts = [p for p in [user.first_name, user.last_name] if p]
            name = " ".join(parts) if parts else f"id{tg_id}"
        description = f"{tournament_title} — {name}" if name else tournament_title

        try:
            result = self.payment_svc.create_payment(tg_id, tournament_id, description)
        except Exception:
            logger.exception("YooKassa create_payment failed for tg_id=%s tournament=%s", tg_id, tournament_id)
            return HandlerResult(PAYMENT_ERROR, is_alert=True)

        text = (
            f"💳 Оплата взноса — {result.amount} руб.\n\n"
            f"Ссылка действует 1 час.\n"
            f"После оплаты ты автоматически появишься в подтверждённом списке."
        )
        return HandlerResult(text, keyboard=self.keyboards.pay_keyboard(result.url), yookassa_id=result.yookassa_id)
