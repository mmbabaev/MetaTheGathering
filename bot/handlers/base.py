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
    yookassa_id: Optional[str] = None  # set after successful payment creation
    answer_text: Optional[str] = None  # short popup shown via query.answer(show_alert=True)
    new_round_numbers: Optional[list[int]] = None  # rounds first seen in this import (opponent DMs)
