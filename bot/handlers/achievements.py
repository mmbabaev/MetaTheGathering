"""Полка ачивок — чистая логика команды /achievements.

Пока ачивки в теневом режиме (флаг ``achievementsPublicUi`` выключен), команда отвечает
только владельцу и админам: игроки не должны видеть фичу, которую мы ещё проверяем.
Админ может посмотреть чужую полку — `/achievements Иванов` — это основной способ
сверить выдачу с историей игрока.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.features import FeatureService
from bot.handlers.base import HandlerResult
from bot.messages import (
    ACHIEVEMENTS_EMPTY,
    ACHIEVEMENTS_HEADER,
    ACHIEVEMENTS_LOCKED_TITLE,
    ACHIEVEMENTS_PLAYER_NOT_FOUND,
    ACHIEVEMENTS_PROGRESS_TITLE,
    ACHIEVEMENTS_UNAVAILABLE,
    ACHIEVEMENTS_UNLOCKED_TITLE,
)
from services.achievement_image import ShelfItem
from services.achievements import AchievementService, AchievementView
from services.achievements.definitions import CODE_ORDER
from services.user import UserService


@dataclass(frozen=True)
class Shelf:
    """Полка игрока: заголовок + все определения со статусом."""

    title: str
    views: list[AchievementView]

    def image_items(self) -> list[ShelfItem]:
        """Ячейки для картинки: по одной на ачивку, а не на каждый уровень.

        Показываем самый высокий открытый уровень (или первый закрытый, если открытых нет),
        а подписью — путь к следующему: «7/10». Иначе 20 медальонов вместо 7 превращают полку
        в простыню, где не видно, что у игрока вообще есть.
        """
        by_code: dict[str, list[AchievementView]] = {}
        for view in self.views:
            by_code.setdefault(view.definition.code, []).append(view)

        items: list[ShelfItem] = []
        for code in CODE_ORDER:
            levels = by_code.get(code)
            if not levels:
                continue
            unlocked = [v for v in levels if v.unlocked]
            current = unlocked[-1] if unlocked else levels[0]
            items.append(
                ShelfItem(
                    definition=current.definition,
                    unlocked=bool(unlocked),
                    caption=_shelf_caption(levels, current),
                )
            )
        return items


def _shelf_caption(levels: list[AchievementView], current: AchievementView) -> str:
    """«7/10» до следующего уровня, иначе «открыто» / «закрыто»."""
    nxt = next((v for v in levels if not v.unlocked), None)
    if nxt is not None and nxt.progress and nxt.definition.threshold:
        return f"{nxt.progress}/{nxt.definition.threshold}"
    if current.unlocked:
        return "всё открыто" if nxt is None else "открыто"
    return "закрыто"


class AchievementsHandler:
    def __init__(self, svc: AchievementService, user_svc: UserService, features: FeatureService) -> None:
        self.svc = svc
        self.user_svc = user_svc
        self.features = features

    def handle_achievements(self, tg_id: int, query: Optional[str] = None) -> HandlerResult:
        """Полка ачивок текстом: своя или (для админов) названного игрока."""
        shelf = self.shelf(tg_id, query)
        if isinstance(shelf, HandlerResult):
            return shelf
        return HandlerResult(format_shelf(shelf.title, shelf.views))

    def shelf(self, tg_id: int, query: Optional[str] = None) -> "Shelf | HandlerResult":
        """Данные полки или готовый отказ (нет прав / игрок не найден).

        Отдельно от ``handle_achievements``, чтобы Telegram-слой мог нарисовать картинку
        по тем же данным, не повторяя проверки доступа.
        """
        is_admin = self.user_svc.is_admin(tg_id)
        if not is_admin and not self.features.is_achievements_ui_public():
            return HandlerResult(ACHIEVEMENTS_UNAVAILABLE)

        if query and is_admin:
            user = self.user_svc.find_by_name(query)
            if user is None:
                return HandlerResult(ACHIEVEMENTS_PLAYER_NOT_FOUND.format(query=query))
        else:
            user = self.user_svc.get_by_tg_id(tg_id)
            if user is None:
                return HandlerResult(ACHIEVEMENTS_EMPTY)

        views = self.svc.list_for_user(user.id)
        return Shelf(title=self._title(user, own=query is None or not is_admin), views=views)

    @staticmethod
    def _title(user, *, own: bool) -> str:
        if own:
            return "Твои ачивки"
        full = " ".join(p for p in (user.last_name, user.first_name) if p).strip()
        return f"Ачивки: {full or user.username or f'id{user.tg_id}'}"


def format_shelf(title: str, views: list[AchievementView]) -> str:
    """Три секции: открытые, в процессе, закрытые."""
    unlocked = [v for v in views if v.unlocked]
    lines = [ACHIEVEMENTS_HEADER.format(title=title, unlocked=len(unlocked), total=len(views)), ""]

    if unlocked:
        lines.append(ACHIEVEMENTS_UNLOCKED_TITLE)
        for view in unlocked:
            definition = view.definition
            lines.append(f"{definition.icon} {definition.title_with_level} — {definition.description}")
            if view.evidence:
                lines.append(f"   {view.evidence}")
        lines.append("")

    in_progress = [v for v in views if not v.unlocked and v.progress]
    if in_progress:
        lines.append(ACHIEVEMENTS_PROGRESS_TITLE)
        for view in _first_level_only(in_progress):
            definition = view.definition
            threshold = definition.threshold or 0
            lines.append(f"{definition.icon} {definition.title_with_level} — {view.progress}/{threshold}")
        lines.append("")

    locked = [v for v in views if not v.unlocked and not v.progress]
    if locked:
        lines.append(ACHIEVEMENTS_LOCKED_TITLE)
        for view in _first_level_only(locked):
            lines.append(f"{view.definition.icon} {view.definition.title_with_level} — {view.definition.hint}")

    return "\n".join(lines).strip()


def _first_level_only(views: list[AchievementView]) -> list[AchievementView]:
    """Из нескольких закрытых уровней одной ачивки показываем только ближайший."""
    seen: set[str] = set()
    result: list[AchievementView] = []
    for view in views:
        if view.definition.code in seen:
            continue
        seen.add(view.definition.code)
        result.append(view)
    return result
