"""
Логгер событий бота.

Интерфейс: event_logger.log(event, tg_id=..., username=..., **params)
Бэкенд задаётся один раз при старте через _build_logger().
Для замены реализации (Monium, БД, webhook) — реализуйте EventBackend и
поменяйте _build_logger().

Использование:
    from core.event_log import event_logger
    event_logger.log("register", tg_id=123, username="mbabaev", tournament_id=5, archetype="Burn")
"""

import json
import logging
import threading
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).parent.parent / "events.jsonl"


# ---------------------------------------------------------------------------
# Интерфейс бэкенда
# ---------------------------------------------------------------------------


class EventBackend(ABC):
    @abstractmethod
    def send(self, entry: dict) -> None:
        """Отправить одно событие. Не должен бросать исключения."""


# ---------------------------------------------------------------------------
# JSONL-бэкенд (файловый, дефолт)
# ---------------------------------------------------------------------------


class JsonlBackend(EventBackend):
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()

    def send(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:
            logger.warning("JsonlBackend write failed: %s", exc)


# ---------------------------------------------------------------------------
# Monium-бэкенд
# ---------------------------------------------------------------------------


class MoniumBackend(EventBackend):
    """Отправляет события в Monium через HTTP POST (fire-and-forget, отдельный поток)."""

    _URL = "https://api.monium.io/v1/events"

    def __init__(self, project: str, api_key: str) -> None:
        self._project = project
        self._api_key = api_key

    def send(self, entry: dict) -> None:
        threading.Thread(target=self._post, args=(dict(entry),), daemon=True).start()

    def _post(self, entry: dict) -> None:
        try:
            payload = json.dumps({"project": self._project, "event": entry}, ensure_ascii=False).encode()
            req = urllib.request.Request(
                self._URL,
                data=payload,
                headers={"Content-Type": "application/json", "X-Api-Key": self._api_key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as exc:
            logger.warning("MoniumBackend send failed: %s", exc)


# ---------------------------------------------------------------------------
# Мультиплексор — пишет во все бэкенды
# ---------------------------------------------------------------------------


class MultiBackend(EventBackend):
    def __init__(self, backends: list[EventBackend]) -> None:
        self._backends = backends

    def send(self, entry: dict) -> None:
        for b in self._backends:
            b.send(entry)


# ---------------------------------------------------------------------------
# Основной EventLogger — тонкая обёртка поверх бэкенда
# ---------------------------------------------------------------------------


class EventLogger:
    def __init__(self, backend: EventBackend) -> None:
        self._backend = backend

    def log(
        self,
        event: str,
        *,
        tg_id: int | None = None,
        username: str | None = None,
        **params,
    ) -> None:
        entry: dict = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": event}
        if tg_id is not None:
            entry["tg_id"] = tg_id
        if username:
            entry["username"] = username
        entry.update(params)

        self._backend.send(entry)

        if settings.DEBUG:
            logger.debug("EVENT %s", json.dumps(entry, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Инициализация — добавь MoniumBackend сюда когда будет готов API
# ---------------------------------------------------------------------------


def _build_logger() -> EventLogger:
    backends: list[EventBackend] = [JsonlBackend()]
    if settings.MONIUM_PROJECT and settings.MONIUM_API_KEY:
        backends.append(MoniumBackend(settings.MONIUM_PROJECT, settings.MONIUM_API_KEY))
    return EventLogger(MultiBackend(backends))


event_logger = _build_logger()
