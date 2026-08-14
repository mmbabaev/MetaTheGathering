import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

_bot_env = os.getenv("BOT_ENV", "prod")
_env_file = "bot/.env.debug" if _bot_env == "debug" else "bot/.env"
load_dotenv(_env_file)


def _is_pytest_running() -> bool:
    # We need this to work during test collection/import time (before any test runs),
    # so PYTEST_CURRENT_TEST is not reliable here.
    if "pytest" in sys.modules:
        return True
    return any("pytest" in (arg or "") for arg in sys.argv)


if _bot_env == "debug":
    from config.debug import app_config as _app_cfg
else:
    from config.prod import app_config as _app_cfg


@dataclass
class ClubSchedule:
    weekday: str  # "friday"
    game_time: str  # "19:30"
    create_time: Optional[str] = None  # overrides TOURNAMENT_CREATE_TIME if set
    aetherhub_fetch_times: List[str] = field(default_factory=list)  # ["20:15", "21:00"]
    find_latest: bool = False  # if True: import latest pauper, ignore date (debug only)
    reminder_time: Optional[str] = None  # "HH:MM" — напоминание «запишите колоду» перед стартом; None = нет


@dataclass
class Club:
    name: str
    chat_id: int
    schedules: List[ClubSchedule]
    aetherhub_url: Optional[str] = None  # https://aetherhub.com/User/GoldFish
    title_prefix: str = ""


class Settings(BaseSettings):
    # In tests we don't want env requirements to block imports.
    TELEGRAM_BOT_TOKEN: str = "TEST_TOKEN" if _is_pytest_running() else ...
    DATABASE_URL: AnyUrl = "sqlite+pysqlite:///:memory:" if _is_pytest_running() else ...

    # Прокси для запросов к Telegram API. Пусто = напрямую.
    # Пример: socks5://127.0.0.1:1080
    TELEGRAM_PROXY_URL: str = ""

    # Через запятую в .env: ADMIN_IDS=123,456
    # Кто есть кто: 232778570 = mbabaev (владелец).
    ADMIN_IDS: str = ""

    MONIUM_PROJECT: str = ""
    MONIUM_API_KEY: str = ""

    # Публичный backend Magic Oculus; несекретно, можно переопределить для debug/staging.
    MAGIC_OCULUS_API_URL: str = "https://bbani33dmiqrgjm2k8fa.containers.yandexcloud.net"
    # Пользовательский frontend для ссылок в Telegram и CLI.
    MAGIC_OCULUS_PUBLIC_URL: str = "https://magicoculus.ru"

    # Структурированные owner-отчёты ачивок для послетурнирного аудита.
    # Пустая строка отключает файловый лог (по умолчанию так только внутри pytest).
    ACHIEVEMENT_LOG_DIR: str = "" if _is_pytest_running() else "logs/achievements"

    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    PAYMENT_AMOUNT: str = "525.00"

    # Web UI
    WEB_SECRET_KEY: str = "dev-secret-change-in-prod"
    WEB_BASE_URL: str = "http://localhost:8080"
    WEB_PORT: int = 8080
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "MetaGatherer <noreply@example.com>"

    # Несекретные настройки — берутся из config/prod.py или config/debug.py
    DEBUG: bool = _app_cfg.debug
    TOURNAMENT_TIMEZONE: str = _app_cfg.tournament_timezone
    TOURNAMENT_CREATE_TIME: str = _app_cfg.tournament_create_time
    VERSION: str = _app_cfg.version
    # Личка владельца для служебных анонсов (создан турнир, колоды раскрыты). Несекретно — в коде, не в .env.
    OWNER_CHAT_ID: Optional[int] = _app_cfg.owner_chat_id

    model_config = SettingsConfigDict(env_file=_env_file, env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def notify_allowed_ids(self) -> Optional[List[int]]:
        """None = все разрешены (прод). Список = только указанные (дебаг)."""
        return _app_cfg.notify_allowed_ids

    @property
    def chat_ids(self) -> List[int]:
        """Все известные chat_id клубов."""
        ids = []
        if _app_cfg.goldfish_chat_id:
            ids.append(_app_cfg.goldfish_chat_id)
        if _app_cfg.edinorog_chat_id:
            ids.append(_app_cfg.edinorog_chat_id)
        if _app_cfg.pair_of_dice_chat_id:
            ids.append(_app_cfg.pair_of_dice_chat_id)
        return ids


settings = Settings()
app_cfg = _app_cfg
