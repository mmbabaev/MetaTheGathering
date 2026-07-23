"""Статистика приложения для владельца (issue: /app_statistics).

Метрики по пользователям/использованию бота. Отделено от services/stats.py, который считает
метагейм турниров. Сюда добавляются новые метрики по мере надобности.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models


class AppStatsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def notify_rounds_count(self) -> int:
        """Сколько реальных игроков включили уведомления о раундах (оппоненте)."""
        return self.db.execute(
            select(func.count())
            .select_from(models.User)
            .where(models.User.notify_opponent_rounds.is_(True), models.User.tg_id > 0)
        ).scalar_one()

    def notify_rounds_users(self) -> list[models.User]:
        """Игроки с включёнными уведомлениями о раундах, отсортированы по имени."""
        return list(
            self.db.execute(
                select(models.User)
                .where(models.User.notify_opponent_rounds.is_(True), models.User.tg_id > 0)
                .order_by(models.User.first_name, models.User.last_name)
            )
            .scalars()
            .all()
        )
