import logging

from fastapi import FastAPI, HTTPException, Request
from telegram import Bot

from core.config import settings
from core.database import SessionLocal
from services.payment_service import PaymentService

logger = logging.getLogger(__name__)

app = FastAPI(title="MetaGatherer API", docs_url=None, redoc_url=None)

PAYMENT_SUCCESS_TEXT = "✅ Оплата подтверждена! Взнос принят."


@app.post("/webhook/yookassa")
async def yookassa_webhook(request: Request) -> dict:
    data = await request.json()
    logger.info("YooKassa webhook: event=%s", data.get("event"))

    db = SessionLocal()
    try:
        result = PaymentService(db).handle_webhook(data)
    except Exception:
        logger.exception("Error processing YooKassa webhook")
        raise HTTPException(status_code=500, detail="internal error")
    finally:
        db.close()

    if result is None:
        return {"ok": True}

    logger.info("Payment succeeded for tg_id=%s", result.tg_id)

    async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
        if result.tg_chat_id and result.tg_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=result.tg_chat_id,
                    message_id=result.tg_message_id,
                    text=PAYMENT_SUCCESS_TEXT,
                )
            except Exception:
                logger.exception("Failed to edit payment message, falling back to new message")
                await bot.send_message(chat_id=result.tg_id, text=PAYMENT_SUCCESS_TEXT)
        else:
            await bot.send_message(chat_id=result.tg_id, text=PAYMENT_SUCCESS_TEXT)

    return {"ok": True}
