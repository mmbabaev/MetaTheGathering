"""Telegram deeplinks: `t.me/<bot>?start=<payload>`.

Поддерживаются переход в запись своей колоды (`deck_<id>`), общая регистрация
(`register_<id>`), текущий раунд (`round_<id>`), помощь мета-полиции (`fill_<id>`)
и меню ячейки (`cellar`).
"""

from __future__ import annotations

from typing import Optional

_DECK_PREFIX = "deck_"
_REGISTER_PREFIX = "register_"
_ROUND_PREFIX = "round_"
_FILL_MISSING_PREFIX = "fill_"
_CELLAR_PAYLOAD = "cellar"


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


def round_payload(tournament_id: int) -> str:
    return f"{_ROUND_PREFIX}{tournament_id}"


def parse_round_payload(payload: str) -> Optional[int]:
    if not payload or not payload.startswith(_ROUND_PREFIX):
        return None
    rest = payload[len(_ROUND_PREFIX) :]
    return int(rest) if rest.isascii() and rest.isdigit() else None


def round_deeplink(bot_username: str, tournament_id: int) -> str:
    return f"https://t.me/{bot_username}?start={round_payload(tournament_id)}"


def fill_missing_payload(tournament_id: int) -> str:
    """start-payload кнопки мета-полиции «Записать»."""
    return f"{_FILL_MISSING_PREFIX}{tournament_id}"


def parse_fill_missing_payload(payload: str) -> Optional[int]:
    """tournament_id из deeplink мета-полиции, либо None."""
    if not payload or not payload.startswith(_FILL_MISSING_PREFIX):
        return None
    rest = payload[len(_FILL_MISSING_PREFIX) :]
    return int(rest) if rest.isascii() and rest.isdigit() else None


def fill_missing_deeplink(bot_username: str, tournament_id: int) -> str:
    """Ссылка из напоминания: открыть выбор своей либо чужой пустой колоды."""
    return f"https://t.me/{bot_username}?start={fill_missing_payload(tournament_id)}"


def is_cellar_payload(payload: str) -> bool:
    """True only for the exact cellar-menu start payload."""

    return payload == _CELLAR_PAYLOAD


def cellar_deeplink(bot_username: str) -> str:
    """Open the bot directly in the cellar date menu."""

    return f"https://t.me/{bot_username}?start={_CELLAR_PAYLOAD}"
