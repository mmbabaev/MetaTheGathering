import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env early so BOT_ENV is available via os.getenv before Settings() runs
load_dotenv()

_bot_env = os.getenv("BOT_ENV", "prod")
if _bot_env == "debug":
    from config import debug as _app_cfg
else:
    from config import prod as _app_cfg


@dataclass
class ClubConfig:
    name: str        # "Goldfish"
    weekday: str     # "thursday"
    chat_id: int
    game_time: str   # "19:30" — время самого турнира (для заголовка)


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    DATABASE_URL: AnyUrl

    # Через запятую в .env: ADMIN_IDS=123,456
    ADMIN_IDS: str = ""

    # Chat ID для каждого клуба — задаются в .env
    GOLDFISH_CHAT_ID: Optional[int] = None
    EDINOROG_CHAT_ID: Optional[int] = None

    MONIUM_PROJECT: str = ""
    MONIUM_API_KEY: str = ""

    # Несекретные настройки — берутся из config/prod.py или config/debug.py
    DEBUG: bool = _app_cfg.DEBUG
    TOURNAMENT_TIMEZONE: str = _app_cfg.TOURNAMENT_TIMEZONE
    TOURNAMENT_CREATE_TIME: str = _app_cfg.TOURNAMENT_CREATE_TIME
    VERSION: str = _app_cfg.VERSION

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def chat_ids(self) -> List[int]:
        """Все известные chat_id клубов."""
        ids = []
        if self.GOLDFISH_CHAT_ID:
            ids.append(self.GOLDFISH_CHAT_ID)
        if self.EDINOROG_CHAT_ID:
            ids.append(self.EDINOROG_CHAT_ID)
        return ids


settings = Settings()
