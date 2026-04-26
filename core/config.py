import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env early so BOT_ENV is available via os.getenv before Settings() runs
load_dotenv()


def _is_pytest_running() -> bool:
    # We need this to work during test collection/import time (before any test runs),
    # so PYTEST_CURRENT_TEST is not reliable here.
    if "pytest" in sys.modules:
        return True
    return any("pytest" in (arg or "") for arg in sys.argv)


_bot_env = os.getenv("BOT_ENV", "prod")
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

    # Через запятую в .env: ADMIN_IDS=123,456
    ADMIN_IDS: str = ""

    # Telegram ID для получения уведомлений о создании турниров (личка)
    ANNOUNCE_CHAT_ID: Optional[int] = None

    MONIUM_PROJECT: str = ""
    MONIUM_API_KEY: str = ""

    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    PAYMENT_AMOUNT: str = "525.00"

    # Несекретные настройки — берутся из config/prod.py или config/debug.py
    DEBUG: bool = _app_cfg.debug
    TOURNAMENT_TIMEZONE: str = _app_cfg.tournament_timezone
    TOURNAMENT_CREATE_TIME: str = _app_cfg.tournament_create_time
    VERSION: str = _app_cfg.version

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
        return ids


settings = Settings()
app_cfg = _app_cfg
