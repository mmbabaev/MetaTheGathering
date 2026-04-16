from dataclasses import dataclass
from typing import List, Optional

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class ClubConfig:
    name: str        # "Goldfish"
    weekday: str     # "thursday"
    chat_id: int
    game_time: str   # "19:30" — время самого турнира (для заголовка)


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    DATABASE_URL: AnyUrl
    DEBUG: bool = False

    # Через запятую в .env: ADMIN_IDS=123,456
    ADMIN_IDS: str = ""

    TOURNAMENT_TIMEZONE: str = "Europe/Moscow"

    # Время создания сущности турнира (утро дня турнира)
    TOURNAMENT_CREATE_TIME: str = "10:00"

    # Chat ID для каждого клуба — задаются в .env
    GOLDFISH_CHAT_ID: Optional[int] = None
    EDINOROG_CHAT_ID: Optional[int] = None

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
