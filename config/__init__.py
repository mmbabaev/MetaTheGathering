from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AppConfig:
    debug: bool
    tournament_timezone: str
    tournament_create_time: str
    version: str = "0.2.0"
    notify_allowed_ids: Optional[List[int]] = None  # None = все разрешены (прод)
    goldfish_chat_id: Optional[int] = None
    edinorog_chat_id: Optional[int] = None
    pair_of_dice_chat_id: Optional[int] = None
    owner_chat_id: Optional[int] = None  # личка владельца бота для служебных анонсов (создан турнир, колоды раскрыты)
