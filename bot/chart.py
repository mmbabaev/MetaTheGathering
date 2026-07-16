"""Безопасная сборка картинок бота (график метагейма, стендинги) для async-кода.

Одно место на всех, кто рисует и шлёт картинку (кнопки админа и анонс «сбор завершён»):
и последовательность «данные → рисование в потоке» одна, и правила безопасности одни.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from services.meta_chart import ChartSector, MetaChartService, render_sectors
from services.standings_image import StandingsImageService, render_standings_pages

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedImage:
    """Готовая картинка."""

    png: bytes
    filename: str


@dataclass(frozen=True)
class RenderedChart(RenderedImage):
    """График + секторы, из которых он собран (чтобы не считать мету дважды)."""

    sectors: list[ChartSector]


async def _safe_build(db, tournament_id: int, prepare: Callable, render: Callable, label: str):
    """Готовит данные в текущем потоке, рисует в отдельном. None — данных нет или сбой.

    Никогда не бросает: картинка — украшение, она не должна ломать ни кнопку, ни анонс.
    Разделение обязательно: сессию SQLAlchemy в поток уносить нельзя (потому `prepare`
    здесь), а рисование (~180 мс CPU) на event loop оставлять нельзя (потому `to_thread`).
    При сбое БД откатываем сессию — `prepare` мог в неё писать (кэш цветов), и отравленная
    сессия дальше уронила бы, например, коммит флага идемпотентности анонса.

    Возвращает (data, png) — вызывающий сам обернёт в нужный тип.
    """
    try:
        data = prepare(tournament_id)
    except Exception:
        logger.exception("%s: failed to collect data for #%s", label, tournament_id)
        db.rollback()
        return None
    if data is None:
        return None
    try:
        png = await asyncio.to_thread(render, data)
    except Exception:
        logger.exception("%s: failed to render for #%s", label, tournament_id)
        return None
    return data, png


async def build_chart(db, tournament_id: int, chart_svc: Optional[MetaChartService] = None) -> Optional[RenderedChart]:
    """График «Метагейм-срез» турнира или None — колод нет либо что-то сломалось."""
    svc = chart_svc if chart_svc is not None else MetaChartService(db)
    result = await _safe_build(
        db, tournament_id, svc.prepare, lambda d: render_sectors(d.sectors, d.subtitle), "build_chart"
    )
    if result is None:
        return None
    data, png = result
    return RenderedChart(png=png, filename=data.filename, sectors=data.sectors)


async def build_standings(
    db, tournament_id: int, standings_svc: Optional[StandingsImageService] = None
) -> list[RenderedImage]:
    """Страницы итоговых стендингов (по 30 игроков). Пустой список — стендингов нет либо сбой."""
    svc = standings_svc if standings_svc is not None else StandingsImageService(db)
    result = await _safe_build(
        db, tournament_id, svc.prepare, lambda d: render_standings_pages(d.rows, d.subtitle), "build_standings"
    )
    if result is None:
        return []
    data, pages = result
    return [RenderedImage(png=png, filename=f"{data.filename_prefix}_{i + 1}.png") for i, png in enumerate(pages)]
