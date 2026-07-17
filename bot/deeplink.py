"""Telegram deeplinks: `t.me/<bot>?start=<payload>`.

Пока один тип — переход сразу в запись колоды на турнир (`deck_<id>`): игрок жмёт кнопку
в анонсе/напоминании и попадает в выбор архетипа, не листая /tournaments.
"""

from __future__ import annotations

from typing import Optional

_DECK_PREFIX = "deck_"


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
