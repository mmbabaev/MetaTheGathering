from dataclasses import dataclass
from typing import Optional

from telegram import InlineKeyboardMarkup


@dataclass
class HandlerResult:
    text: str
    keyboard: Optional[InlineKeyboardMarkup] = None
    is_alert: bool = False
