"""Построение графика «Метагейм-срез» для async-кода бота.

Одно место на всех, кто шлёт график (кнопка админа и анонс «сбор завершён»):
и последовательность «данные → рисование в потоке» одна, и правила безопасности одни.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from services.meta_chart import ChartSector, MetaChartService, render_sectors

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedChart:
    """Готовая картинка + секторы, из которых она собрана (чтобы не считать мету дважды)."""

    png: bytes
    filename: str
    sectors: list[ChartSector]


async def build_chart(db, tournament_id: int, chart_svc: Optional[MetaChartService] = None) -> Optional[RenderedChart]:
    """График турнира или None — колод нет либо что-то сломалось. Никогда не бросает.

    Разделение обязательное:
    - работа с БД (`prepare`) остаётся в вызывающем потоке — сессия SQLAlchemy не
      предназначена для переезда между потоками;
    - рисование (~180 мс чистого CPU) уходит в поток, иначе заморозит event loop всему боту.

    Ошибку глушим: график — украшение, и он не должен ломать ни кнопку, ни анонс.
    Но при сбое обязательно откатываем сессию: `prepare` пишет в БД (кэш цветов), и
    отравленная сессия дальше уронила бы, например, коммит флага идемпотентности.
    """
    try:
        data = (chart_svc if chart_svc is not None else MetaChartService(db)).prepare(tournament_id)
    except Exception:
        logger.exception("build_chart: failed to collect chart data for #%s", tournament_id)
        db.rollback()
        return None

    if data is None:
        return None

    try:
        png = await asyncio.to_thread(render_sectors, data.sectors, data.subtitle)
    except Exception:
        logger.exception("build_chart: failed to render chart for #%s", tournament_id)
        return None

    return RenderedChart(png=png, filename=data.filename, sectors=data.sectors)
