"""Форматирование ФИО игрока в «Фамилия Имя» — общая логика для всех поверхностей.

Живёт в services (ниже bot), чтобы одинаково использоваться и в UI (`bot/messages`),
и в картинках (`services/standings_image`), без расхождений в порядке имени.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
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


def clean_person_name_component(value: str | None) -> str | None:
    """Trim whitespace and decorative emoji around a person-name component."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    while cleaned and (
        unicodedata.category(cleaned[0]).startswith(("P", "S")) or unicodedata.category(cleaned[0]) in {"Cf", "Mn"}
    ):
        cleaned = cleaned[1:].lstrip()
    while cleaned and (
        unicodedata.category(cleaned[-1]).startswith(("P", "S")) or unicodedata.category(cleaned[-1]) in {"Cf", "Mn"}
    ):
        cleaned = cleaned[:-1].rstrip()
    return re.sub(r"\s+", " ", cleaned).strip() or None


def _valid_name_words(value: str | None) -> list[str] | None:
    cleaned = clean_person_name_component(value)
    if not cleaned:
        return None
    words = cleaned.split()
    if len(words) < 2 or any(not any(char.isalpha() for char in word) for word in words):
        return None
    return words


def parse_full_name_input(value: str) -> tuple[str, str] | None:
    """Parse UI input in ``Фамилия Имя`` order after strict validation."""
    words = _valid_name_words(value)
    if words is None:
        return None
    return " ".join(words[1:]), words[0]


def has_complete_person_name(first_name: str | None, last_name: str | None) -> bool:
    """Whether stored Telegram/user fields contain at least two letter-bearing words."""
    first = clean_person_name_component(first_name)
    last = clean_person_name_component(last_name)
    return _valid_name_words(" ".join(part for part in (last, first) if part)) is not None


def looks_like_family_name(word: str) -> bool:
    w = word.lower()
    return any(w.endswith(s) for s in _FAMILY_SUFFIXES)


def normalized_name_words(value: str) -> tuple[str, ...]:
    """Слова ФИО без учёта порядка, регистра и различия ё/е."""
    return tuple(sorted(value.strip().casefold().replace("ё", "е").split()))


def _is_one_edit_apart(left: str, right: str) -> bool:
    """Ровно одна вставка, потеря или замена символа."""
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_i = long_i = differences = 0
    while short_i < len(shorter) and long_i < len(longer):
        if shorter[short_i] == longer[long_i]:
            short_i += 1
            long_i += 1
            continue
        differences += 1
        if differences > 1:
            return False
        long_i += 1
    return True


def is_single_word_name_typo(imported_name: str, candidate_name: str) -> bool:
    """Два слова: одно совпало точно, второе длинное отличается на один символ."""
    imported = normalized_name_words(imported_name)
    candidate = normalized_name_words(candidate_name)
    if len(imported) != 2 or len(candidate) != 2:
        return False
    shared = Counter(imported) & Counter(candidate)
    if sum(shared.values()) != 1:
        return False
    imported_diff = next(iter((Counter(imported) - shared).elements()))
    candidate_diff = next(iter((Counter(candidate) - shared).elements()))
    return min(len(imported_diff), len(candidate_diff)) >= 5 and _is_one_edit_apart(imported_diff, candidate_diff)


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
