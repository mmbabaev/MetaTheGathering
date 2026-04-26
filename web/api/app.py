import logging

from fastapi import FastAPI, HTTPException, Request

from core.database import SessionLocal
from services.payment_service import PaymentService

logger = logging.getLogger(__name__)

app = FastAPI(title="MetaGatherer API", docs_url=None, redoc_url=None)


@app.post("/webhook/yookassa")
async def yookassa_webhook(request: Request) -> dict:
    data = await request.json()
    logger.info("YooKassa webhook: event=%s", data.get("event"))

    db = SessionLocal()
    try:
        tg_id = PaymentService(db).handle_webhook(data)
    except Exception:
        logger.exception("Error processing YooKassa webhook")
        raise HTTPException(status_code=500, detail="internal error")
    finally:
        db.close()

    if tg_id is not None:
        logger.info("Payment succeeded for tg_id=%s", tg_id)

    return {"ok": True}
