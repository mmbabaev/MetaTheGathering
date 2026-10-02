"""Алерты о том, что фоновая задача не сделала свою работу.

Зачем абстракция: джобы планировщика молча ломались. Реальный случай — 02.10.2026,
Goldfish: два турнира зависли в `REGISTRATION` (AetherHub не отдал счёт → авто-закрытие
не сработало), лимит активных турниров был исчерпан, и `CreateTournamentJob` в 12:00
просто написал WARNING в лог — турнир не создался, и никто об этом не узнал.

Контракт намеренно узкий: джоба говорит «я не выполнила задачу и вот почему», а кто и
куда это доставляет — решение слоя доставки. Сегодня реализация одна,
`OwnerDmJobAlerts` (личка владельца). Завтра это может быть Sentry, email или чат
админов: достаточно добавить класс-наследник и зарегистрировать его в `_BACKENDS`,
ничего не меняя в самих джобах.

Безопасность (жёсткие правила из AGENTS.md):
  * доставка только владельцу (`settings.OWNER_CHAT_ID`), никому другому;
  * `notify_allowed_ids` — гейт: если владелец не в списке разрешённых, молчим;
  * троттлинг: одна и та же причина не повторяется внутри окна (по умолчанию 6 ч), иначе
    сломанная джоба завалит личку десятками одинаковых сообщений.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from core.config import settings

logger = logging.getLogger(__name__)

# Сколько не повторять одну и ту же причину. Дожим: джоба может не сработать много раз
# подряд (каждый день в 12:00), а владельцу достаточно одного сообщения и времени починить.
ALERT_THROTTLE_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class JobAlert:
    """Одна «джоба не выполнила задачу» — с причиной и техническим деталем."""

    job: str
    """Имя джобы, как её видит планировщик: `create_tournament[Goldfish/friday]`."""

    reason: str
    """Короткая причина машиночитаемо: `limit_reached`, `wrong_weekday`, `error`."""

    summary: str
    """Что случилось человеческим языком — это попадёт в сообщение."""

    detail: str | None = None
    """Трассировка/исключение: уходит в лог, а не в личку."""


class JobAlerts(ABC):
    """Куда доставлять алерты джоб. Реализация обязана быть безопасной по умолчанию."""

    @abstractmethod
    async def send(self, alert: JobAlert) -> bool:
        """Доставить алерт. ``True`` — доставлено (или недавно уже доставлялось)."""


class OwnerDmJobAlerts(JobAlerts):
    """Личка владельца — единственная активная реализация."""

    def __init__(
        self,
        *,
        throttle_seconds: int = ALERT_THROTTLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        chat_id: int | None = None,
    ) -> None:
        self._throttle_seconds = throttle_seconds
        self._clock = clock
        self._chat_id = chat_id
        self._bot = None
        self._last_sent: dict[str, float] = {}

    def bind_bot(self, bot) -> None:
        """Джобы получают бота от планировщика; без него доставка невозможна."""
        self._bot = bot

    async def send(self, alert: JobAlert) -> bool:
        if alert.detail:
            logger.error("job alert %s/%s: %s — %s", alert.job, alert.reason, alert.summary, alert.detail)
        else:
            logger.warning("job alert %s/%s: %s", alert.job, alert.reason, alert.summary)

        key = f"{alert.job}|{alert.reason}"
        last = self._last_sent.get(key)
        if last is not None and (self._clock() - last) < self._throttle_seconds:
            logger.info("job alert %s/%s throttled", alert.job, alert.reason)
            return True

        chat_id = self._chat_id if self._chat_id is not None else settings.OWNER_CHAT_ID
        if not chat_id:
            logger.warning("job alert %s/%s skipped: OWNER_CHAT_ID is not set", alert.job, alert.reason)
            return False

        allowed_ids = settings.notify_allowed_ids
        if allowed_ids is not None and chat_id not in allowed_ids:
            logger.warning("job alert %s/%s skipped: owner is not in notify_allowed_ids", alert.job, alert.reason)
            return False

        if self._bot is None:
            logger.warning("job alert %s/%s skipped: no bot bound", alert.job, alert.reason)
            return False

        try:
            await self._bot.send_message(chat_id=chat_id, text=_format(alert))
        except Exception:
            logger.exception("job alert %s/%s delivery failed", alert.job, alert.reason)
            return False

        self._last_sent[key] = self._clock()
        return True


class NullJobAlerts(JobAlerts):
    """Ничего не доставляет — режим без алертов. В тестах ещё и собирает алерты в `.sent`."""

    def __init__(self) -> None:
        self.sent: list[JobAlert] = []

    async def send(self, alert: JobAlert) -> bool:
        self.sent.append(alert)
        return True


def _format(alert: JobAlert) -> str:
    return f"⚠️ Задача не выполнена: {alert.summary}\n\nДжоба: `{alert.job}`\nПричина: `{alert.reason}`"


_BACKENDS: dict[str, type[JobAlerts]] = {
    "owner_dm": OwnerDmJobAlerts,
    "null": NullJobAlerts,
}

_default: JobAlerts | None = None


def get_job_alerts(bot=None) -> JobAlerts:
    """Алерты для джобы. Реализация выбирается в одном месте — её и меняют."""
    global _default
    if _default is None:
        backend = (settings.JOB_ALERTS_BACKEND or "owner_dm").strip()
        _default = _BACKENDS.get(backend, OwnerDmJobAlerts)()
    if bot is not None and isinstance(_default, OwnerDmJobAlerts):
        _default.bind_bot(bot)
    return _default


def set_job_alerts(alerts: JobAlerts | None) -> None:
    """Подменить реализацию (тесты, отключение алертов). ``None`` — вернуть дефолт."""
    global _default
    _default = alerts
