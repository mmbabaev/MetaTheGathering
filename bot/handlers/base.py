from dataclasses import dataclass
from typing import Optional

from telegram import InlineKeyboardMarkup


@dataclass
class HandlerResult:
    text: str
    keyboard: Optional[InlineKeyboardMarkup] = None
    is_alert: bool = False
    needs_name: bool = False  # wrapper должен запросить имя перед продолжением
    parse_mode: Optional[str] = None
    tournament_id: Optional[int] = None  # set when result references a specific tournament
