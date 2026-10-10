from dataclasses import dataclass

from telegram import InlineKeyboardMarkup


@dataclass
class HandlerResult:
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    is_alert: bool = False
    needs_name: bool = False  # wrapper должен запросить имя перед продолжением
    needs_endstep_username: bool = False  # онлайн-турнир требует ник Endstep
    needs_city: bool = False  # ожидается повторный ручной ввод города
    parse_mode: str | None = None
    tournament_id: int | None = None  # set when result references a specific tournament
    creation_plan_id: int | None = None  # set after tournament creation is scheduled
    yookassa_id: str | None = None  # set after successful payment creation
    answer_text: str | None = None  # short popup shown via query.answer(show_alert=True)
    silent: bool = False  # обёртка не отправляет ничего: команда «как будто не существует»
    new_round_numbers: list[int] | None = None  # rounds first seen in this import (opponent DMs)
    broadcast_recipients: list | None = None  # tg_id получателей личной рассылки владельца
