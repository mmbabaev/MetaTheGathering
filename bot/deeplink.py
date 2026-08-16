"""Telegram deeplinks: `t.me/<bot>?start=<payload>`.

Поддерживаются переход в запись колоды (`deck_<id>`) и общая регистрация
(`register_<id>`). Вторая сначала проверяет, не записан ли игрок уже.
"""

from __future__ import annotations

from typing import Optional

_DECK_PREFIX = "deck_"
_REGISTER_PREFIX = "register_"


def deck_payload(tournament_id: int) -> str:
    """start-payload для перехода в запись колоды на турнир."""
    return f"{_DECK_PREFIX}{tournament_id}"


def parse_deck_payload(payload: str) -> Optional[int]:
    """tournament_id из start-payload, либо None, если это не deck-диплинк.

    Требуем именно ASCII-цифры: str.isdigit() пропускает Unicode-цифры (напр. «²»),
    на которых int() бросает ValueError — иначе `/start deck_²` уронил бы обработчик.
    """
    if not payload or not payload.startswith(_DECK_PREFIX):
        return None
    rest = payload[len(_DECK_PREFIX) :]
    return int(rest) if rest.isascii() and rest.isdigit() else None


def deck_deeplink(bot_username: str, tournament_id: int) -> str:
    """Ссылка `https://t.me/<bot>?start=deck_<id>` — открывает бота и ведёт в запись колоды."""
    return f"https://t.me/{bot_username}?start={deck_payload(tournament_id)}"


def registration_payload(tournament_id: int) -> str:
    """start-payload общей кнопки «Записаться»."""
    return f"{_REGISTER_PREFIX}{tournament_id}"


def parse_registration_payload(payload: str) -> Optional[int]:
    """tournament_id из registration start-payload, либо None."""
    if not payload or not payload.startswith(_REGISTER_PREFIX):
        return None
    rest = payload[len(_REGISTER_PREFIX) :]
    return int(rest) if rest.isascii() and rest.isdigit() else None


def registration_deeplink(bot_username: str, tournament_id: int) -> str:
    """Ссылка общей регистрации: записанным показывает статус турнира."""
    return f"https://t.me/{bot_username}?start={registration_payload(tournament_id)}"
