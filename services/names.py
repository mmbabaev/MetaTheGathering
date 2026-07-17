"""Форматирование ФИО игрока в «Фамилия Имя» — общая логика для всех поверхностей.

Живёт в services (ниже bot), чтобы одинаково использоваться и в UI (`bot/messages`),
и в картинках (`services/standings_image`), без расхождений в порядке имени.
"""

from __future__ import annotations

from typing import Optional

_FAMILY_SUFFIXES = (
    "ов",
    "ев",
    "ёв",
    "ин",
    "ын",
    "ый",
    "ий",
    "ой",
    "ский",
    "цкий",
    "ской",
    "ная",
    "ных",
    "ых",
    "ина",
    "ева",
    "ова",
    "ская",
)


def looks_like_family_name(word: str) -> bool:
    w = word.lower()
    return any(w.endswith(s) for s in _FAMILY_SUFFIXES)


def format_participant_name(first_name: Optional[str], last_name: Optional[str]) -> str:
    """«Фамилия Имя».

    Оба поля есть — просто last_name + first_name. Только first_name (Telegram-юзер с именем
    в одном поле) — эвристика: если последнее слово похоже на фамилию (суффикс -ов/-ин/…),
    переставляем; иначе оставляем как есть (первое слово уже фамилия). Пусто — пустая строка.
    """
    if last_name and first_name:
        return f"{last_name} {first_name}"
    if last_name:
        return last_name
    if not first_name:
        return ""
    words = first_name.split()
    if len(words) == 2 and looks_like_family_name(words[1]):
        return f"{words[1]} {words[0]}"
    return first_name


def family_name_sort_key(first_name: Optional[str], last_name: Optional[str]) -> str:
    """Фамилия в нижнем регистре — для сортировки по фамилии."""
    if last_name:
        return last_name.lower()
    if not first_name:
        return ""
    words = first_name.split()
    if len(words) == 2 and looks_like_family_name(words[1]):
        return words[1].lower()
    return (words[0] if words else "").lower()
