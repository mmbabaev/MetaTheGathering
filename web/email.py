import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from core.config import settings

logger = logging.getLogger(__name__)


async def send_magic_link(to_email: str, magic_url: str) -> str | None:
    """Send magic link email. Returns magic_url when SMTP is not configured (for debug display)."""
    if not settings.SMTP_HOST:
        logger.warning("SMTP not configured, magic link for %s: %s", to_email, magic_url)
        return magic_url

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Вход в MetaGatherer"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    text = f"Ваша ссылка для входа:\n{magic_url}\n\nСсылка действительна 15 минут."
    html = f"""<p>Нажмите кнопку для входа в MetaGatherer:</p>
<p><a href="{magic_url}" style="background:#2563eb;color:#fff;padding:10px 20px;
border-radius:6px;text-decoration:none;display:inline-block;">Войти</a></p>
<p style="color:#6b7280;font-size:12px;">Ссылка действительна 15 минут.
Если вы не запрашивали вход — просто проигнорируйте это письмо.</p>"""

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        start_tls=True,
    )
