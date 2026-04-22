import os
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env early so BOT_ENV is available via os.getenv before Settings() runs
load_dotenv()

_bot_env = os.getenv("BOT_ENV", "prod")
if _bot_env == "debug":
    from config.debug import app_config as _app_cfg
else:
    from config.prod import app_config as _app_cfg


@dataclass
class ClubSchedule:
    weekday: str                              # "friday"
    game_time: str                            # "19:30"
    create_time: Optional[str] = None        # overrides TOURNAMENT_CREATE_TIME if set
    aetherhub_fetch_times: List[str] = field(default_factory=list)  # ["20:15", "21:00"]


@dataclass
class Club:
    name: str
    chat_id: int
    schedules: List[ClubSchedule]
    aetherhub_url: Optional[str] = None      # https://aetherhub.com/User/GoldFish
    title_prefix: str = ""


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    DATABASE_URL: AnyUrl

    # Через запятую в .env: ADMIN_IDS=123,456
    ADMIN_IDS: str = ""

    # Chat ID для каждого клуба — задаются в .env или берутся из config/debug.py
    GOLDFISH_CHAT_ID: Optional[int] = _app_cfg.goldfish_chat_id
    EDINOROG_CHAT_ID: Optional[int] = _app_cfg.edinorog_chat_id

    MONIUM_PROJECT: str = ""
    MONIUM_API_KEY: str = ""

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
        if self.GOLDFISH_CHAT_ID:
            ids.append(self.GOLDFISH_CHAT_ID)
        if self.EDINOROG_CHAT_ID:
            ids.append(self.EDINOROG_CHAT_ID)
        return ids


settings = Settings()
