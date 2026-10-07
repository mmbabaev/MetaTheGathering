from dataclasses import dataclass


@dataclass
class AppConfig:
    debug: bool
    tournament_timezone: str
    tournament_create_time: str
    version: str = "0.2.0"
    ranked_missed_entry_penalty: int = 10
    notify_allowed_ids: list[int] | None = None  # None = все разрешены (прод)
    goldfish_chat_id: int | None = None
    edinorog_chat_id: int | None = None
    pair_of_dice_chat_id: int | None = None
    hobby_games_chat_id: int | None = None
    endstep_ru_chat_id: int | None = None
    endstep_draft_chat_id: int | None = None
    owner_chat_id: int | None = None  # личка владельца бота для служебных анонсов (создан турнир, колоды раскрыты)
