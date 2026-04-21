from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AppConfig:
    debug: bool
    tournament_timezone: str
    tournament_create_time: str
    version: str = "0.1.1"
    notify_allowed_ids: Optional[List[int]] = None  # None = все разрешены (прод)
    goldfish_chat_id: Optional[int] = None
    edinorog_chat_id: Optional[int] = None
