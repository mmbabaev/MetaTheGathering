"""
Логгер событий бота.

Пишет структурированные события в JSONL-файл (одна строка = один JSON).
Позже можно заменить backend на БД, webhook, etc. — интерфейс остаётся прежним.

Использование:
    from core.event_log import event_logger
    event_logger.log("register", tg_id=123, username="mbabaev", tournament_id=5, archetype="Burn")
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

# Путь к файлу событий рядом с server.log
_DEFAULT_PATH = Path(__file__).parent.parent / "events.jsonl"


class EventLogger:
    """Пишет события в JSONL-файл.

    Каждая запись:
    {
        "ts":       "2026-04-16T10:00:00Z",
        "event":    "register",
        "tg_id":    232778570,
        "username": "mbabaev",
        ...любые доп. поля...
    }
    """

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()

    def log(
        self,
        event: str,
        *,
        tg_id: int | None = None,
        username: str | None = None,
        **params,
    ) -> None:
        """Записывает событие.

        Args:
            event:    Тип события (например "register", "bulk_add", "set_arch").
            tg_id:    Telegram ID пользователя, который совершил действие.
            username: @username (без @) или None.
            **params: Любые дополнительные параметры (tournament_id, archetype, etc.).
        """
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": event,
        }
        if tg_id is not None:
            entry["tg_id"] = tg_id
        if username:
            entry["username"] = username
        entry.update(params)

        line = json.dumps(entry, ensure_ascii=False)
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("EventLogger write failed: %s", exc)

        if settings.DEBUG:
            logger.debug("EVENT %s", line)


# Глобальный инстанс — используется во всём проекте
event_logger = EventLogger()
