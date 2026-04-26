import logging
import uuid
from dataclasses import dataclass

import requests
from sqlalchemy.orm import Session

from core import models
from core.config import settings

logger = logging.getLogger(__name__)

YOOKASSA_API = "https://api.yookassa.ru/v3/payments"


@dataclass
class PaymentCreated:
    url: str
    amount: str
    yookassa_id: str


@dataclass
class WebhookResult:
    tg_id: int
    tg_chat_id: int | None
    tg_message_id: int | None


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_payment(self, tg_id: int, tournament_id: int, description: str) -> PaymentCreated:
        resp = requests.post(
            YOOKASSA_API,
            json={
                "amount": {"value": settings.PAYMENT_AMOUNT, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://t.me/MetaGathererBot"},
                "description": description,
                "metadata": {"tg_id": str(tg_id), "tournament_id": str(tournament_id)},
                "capture": True,
            },
            auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            headers={"Idempotence-Key": str(uuid.uuid4())},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        payment = models.Payment(
            tg_id=tg_id,
            tournament_id=tournament_id,
            amount=settings.PAYMENT_AMOUNT,
            yookassa_payment_id=data["id"],
            status=models.PaymentStatus.PENDING,
            confirmation_url=data["confirmation"]["confirmation_url"],
        )
        self.db.add(payment)
        self.db.commit()

        return PaymentCreated(
            url=data["confirmation"]["confirmation_url"],
            amount=settings.PAYMENT_AMOUNT,
            yookassa_id=data["id"],
        )

    def is_paid(self, tg_id: int, tournament_id: int) -> bool:
        return (
            self.db.query(models.Payment)
            .filter_by(tg_id=tg_id, tournament_id=tournament_id, status=models.PaymentStatus.SUCCEEDED)
            .first()
            is not None
        )

    def set_message_info(self, yookassa_id: str, tg_chat_id: int, tg_message_id: int) -> None:
        payment = self.db.query(models.Payment).filter_by(yookassa_payment_id=yookassa_id).first()
        if payment:
            payment.tg_chat_id = tg_chat_id
            payment.tg_message_id = tg_message_id
            self.db.commit()

    def handle_webhook(self, data: dict) -> WebhookResult | None:
        """Обрабатывает событие от ЮKassa. Возвращает WebhookResult если платёж прошёл."""
        if data.get("event") != "payment.succeeded":
            return None
        payment_obj = data["object"]
        yookassa_id = payment_obj["id"]
        payment = self.db.query(models.Payment).filter_by(yookassa_payment_id=yookassa_id).first()
        if payment is None:
            logger.warning("webhook: unknown payment %s", yookassa_id)
            return None
        payment.status = models.PaymentStatus.SUCCEEDED
        self.db.commit()
        return WebhookResult(
            tg_id=payment.tg_id,
            tg_chat_id=payment.tg_chat_id,
            tg_message_id=payment.tg_message_id,
        )
