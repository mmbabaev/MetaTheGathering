"""Инварианты реестра definitions/rules: ошибки ловятся до обработки турнира."""

from dataclasses import replace

import pytest

from services.achievements import definitions
from services.achievements.registry import RegistryValidationError, validate_registry
from services.achievements.rules import default_rules


class Rule:
    def __init__(self, code: str) -> None:
        self.code = code


def _valid():
    return list(definitions.all_definitions()), list(definitions.CODE_ORDER), default_rules()


def test_default_registry_is_valid():
    defs, order, rules = _valid()

    validate_registry(defs, order, rules)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda defs, order, rules: (defs + [defs[0]], order, rules), "duplicate definition keys"),
        (lambda defs, order, rules: (defs, order[:-1], rules), "codes missing from CODE_ORDER"),
        (lambda defs, order, rules: (defs, order + [order[0]], rules), "duplicate codes in CODE_ORDER"),
        (
            lambda defs, order, rules: (
                [replace(defs[0], rarity="mythic"), *defs[1:]],
                order,
                rules,
            ),
            "unknown rarity",
        ),
        (
            lambda defs, order, rules: (
                [*defs, replace(defs[0], code="new_code", level=2, threshold=2)],
                [*order, "new_code"],
                [*rules, Rule("new_code")],
            ),
            "must be consecutive from 1",
        ),
        (
            lambda defs, order, rules: (
                [replace(item, threshold=1) if item.code == definitions.Codes.UNDEFEATED else item for item in defs],
                order,
                rules,
            ),
            "must strictly increase",
        ),
        (lambda defs, order, rules: (defs, order, rules[:-1]), "definitions without rules"),
        (lambda defs, order, rules: (defs, order, rules + [rules[0]]), "multiple rules registered"),
        (lambda defs, order, rules: (defs, order, rules + [Rule("ghost")]), "rules without definitions"),
    ],
)
def test_invalid_registry_is_rejected(mutate, message):
    defs, order, rules = _valid()
    changed_defs, changed_order, changed_rules = mutate(defs, order, rules)

    with pytest.raises(RegistryValidationError, match=message):
        validate_registry(changed_defs, changed_order, changed_rules)
