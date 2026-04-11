from typing import List

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    DATABASE_URL: AnyUrl
    DEBUG: bool = False

    # Через запятую в .env: ADMIN_IDS=123,456
    ADMIN_IDS: str = ""

    # Расписание: "weekday HH:MM" или несколько через запятую: "friday 19:00,saturday 12:00"
    TOURNAMENT_SCHEDULE: str = "friday 19:00"
    TOURNAMENT_TIMEZONE: str = "Europe/Moscow"

    # Список chat_id через запятую в .env: TOURNAMENT_CHAT_IDS=123,456
    TOURNAMENT_CHAT_IDS: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()]

    @property
    def schedule_list(self) -> List[str]:
        return [s.strip() for s in self.TOURNAMENT_SCHEDULE.split(",") if s.strip()]

    @property
    def chat_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.TOURNAMENT_CHAT_IDS.split(",") if x.strip()]


settings = Settings()
