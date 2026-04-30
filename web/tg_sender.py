import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


async def send_tg_message(tg_id: int, text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, cannot send TG message to %s", tg_id)
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": tg_id, "text": text},
            timeout=10,
        )
    if not resp.is_success:
        logger.warning("Failed to send TG message to %s: %s", tg_id, resp.text)
    return resp.is_success
