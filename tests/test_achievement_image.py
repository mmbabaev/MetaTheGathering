"""Картинки ачивок: карточка и полка.

Проверяем то же, что и остальные рендеры бота (`test_bot_chart.py`): получается валидный
непустой PNG и раскладка не падает на краевых данных.
"""

import io

import pytest
from PIL import Image

from services.achievement_image import ShelfItem, render_achievement_card, render_shelf
from services.achievements import definitions
from services.achievements.definitions import Codes


def _png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@pytest.fixture
def all_items():
    items = []
    for code in definitions.CODE_ORDER:
        first = definitions.levels_for(code)[0]
        items.append(ShelfItem(definition=first, unlocked=False, caption="закрыто"))
    return items


def test_card_renders_valid_png():
    png = render_achievement_card(
        definitions.get(Codes.UNDEFEATED, 2),
        player="Иванова Алиса",
        evidence="4-0 на Mono Red Madness; всего X-0: 3",
        subtitle="Pauper 24.07.2026 · Goldfish",
    )

    image = _png(png)
    assert image.format == "PNG"
    assert image.size[0] == 1179 and image.size[1] > 400


def test_card_survives_long_texts():
    png = render_achievement_card(
        definitions.get(Codes.SCRIBE, 4),
        player="Длиннофамильный-Через-Дефис Иннокентий",
        evidence="записал сегодня: " + ", ".join(f"Игрок{i}" for i in range(30)),
        subtitle="Очень длинное название турнира которое не влезает никуда · Единорог",
    )

    assert _png(png).format == "PNG"


def test_card_for_one_off_achievement_uses_monogram():
    """У «Дебюта» нет уровней — вместо римской цифры первая буква названия."""
    png = render_achievement_card(definitions.get(Codes.DEBUT, 1), player="Боб")

    assert _png(png).format == "PNG"


def test_shelf_renders_all_achievements(all_items):
    png = render_shelf(all_items, title="Ачивки: Иванова Алиса", subtitle="Goldfish")

    image = _png(png)
    assert image.format == "PNG"
    assert image.size[0] == 1179


def test_shelf_grows_with_rows(all_items):
    short = _png(render_shelf(all_items[:3], title="Полка"))
    tall = _png(render_shelf(all_items, title="Полка"))

    assert tall.size[1] > short.size[1]


def test_shelf_handles_empty_list():
    image = _png(render_shelf([], title="Пока пусто"))

    assert image.format == "PNG"


def test_shelf_marks_unlocked_and_progress():
    items = [
        ShelfItem(definition=definitions.get(Codes.SCRIBE, 1), unlocked=True, caption="7/10"),
        ShelfItem(definition=definitions.get(Codes.REGULAR, 1), unlocked=False, caption="3/4"),
    ]

    assert _png(render_shelf(items, title="Полка")).format == "PNG"
