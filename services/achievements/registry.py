"""Проверка целостности реестра ачивок до начала обработки турнира."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

from services.achievements.definitions import AchievementDef, Rarity


class RegisteredRule(Protocol):
    code: str


class RegistryValidationError(ValueError):
    """Definitions, порядок показа и правила противоречат друг другу."""


def validate_registry(
    definitions: Sequence[AchievementDef],
    code_order: Sequence[str],
    rules: Iterable[RegisteredRule],
) -> None:
    """Проверить инварианты, без которых выдача может стать частичной или упасть после commit."""
    errors: list[str] = []
    definitions_by_code: dict[str, list[AchievementDef]] = defaultdict(list)
    keys = [definition.key for definition in definitions]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicate_keys:
        errors.append(f"duplicate definition keys: {duplicate_keys}")

    known_rarities = {Rarity.COMMON, Rarity.RARE, Rarity.EPIC}
    for definition in definitions:
        definitions_by_code[definition.code].append(definition)
        if not definition.code:
            errors.append("definition code must not be empty")
        elif len(definition.code) > 32:
            errors.append(f"definition code exceeds database limit: {definition.code!r}")
        if definition.rarity not in known_rarities:
            errors.append(f"unknown rarity for {definition.key}: {definition.rarity!r}")

    duplicate_order = sorted(code for code, count in Counter(code_order).items() if count > 1)
    if duplicate_order:
        errors.append(f"duplicate codes in CODE_ORDER: {duplicate_order}")

    definition_codes = set(definitions_by_code)
    order_codes = set(code_order)
    if missing := sorted(definition_codes - order_codes):
        errors.append(f"codes missing from CODE_ORDER: {missing}")
    if unknown := sorted(order_codes - definition_codes):
        errors.append(f"CODE_ORDER contains unknown codes: {unknown}")

    for code, code_definitions in sorted(definitions_by_code.items()):
        ordered = sorted(code_definitions, key=lambda item: item.level)
        levels = [definition.level for definition in ordered]
        expected_levels = list(range(1, len(ordered) + 1))
        if levels != expected_levels:
            errors.append(f"levels for {code!r} must be consecutive from 1: {levels}")

        thresholds = [definition.threshold for definition in ordered]
        if any(threshold is None for threshold in thresholds):
            if len(ordered) != 1 or thresholds != [None]:
                errors.append(f"thresholds for {code!r} must be all positive integers or one None")
            continue
        numeric_thresholds = [int(threshold) for threshold in thresholds]
        if any(threshold <= 0 for threshold in numeric_thresholds):
            errors.append(f"thresholds for {code!r} must be positive: {numeric_thresholds}")
        if any(current >= following for current, following in zip(numeric_thresholds, numeric_thresholds[1:])):
            errors.append(f"thresholds for {code!r} must strictly increase: {numeric_thresholds}")

    rule_codes = [rule.code for rule in rules]
    duplicate_rules = sorted(code for code, count in Counter(rule_codes).items() if count > 1)
    if duplicate_rules:
        errors.append(f"multiple rules registered for codes: {duplicate_rules}")
    if missing := sorted(definition_codes - set(rule_codes)):
        errors.append(f"definitions without rules: {missing}")
    if unknown := sorted(set(rule_codes) - definition_codes):
        errors.append(f"rules without definitions: {unknown}")

    if errors:
        raise RegistryValidationError("Invalid achievement registry: " + "; ".join(errors))
