"""Pure handler for the public Moscow Pauper Ranked leaderboard."""

from bot.handlers.base import HandlerResult
from bot.keyboards import ranked_back_keyboard, ranked_leaderboard_keyboard
from bot.messages import RANKED_RULES_TEXT
from services.feature_flags import FeatureFlags, FeatureFlagService
from services.ranked_leaderboard import RankedLeaderboard, RankedLeaderboardService
from services.user import UserService

LEADERBOARD_PAGE_SIZE = 10


class RankedLeaderboardHandler:
    def __init__(
        self,
        ranked: RankedLeaderboardService,
        users: UserService,
        features: FeatureFlagService,
    ) -> None:
        self.ranked = ranked
        self.users = users
        self.features = features

    def handle_page(self, page: int = 0) -> HandlerResult:
        if not self.features.is_enabled(FeatureFlags.RANKED_PUBLIC):
            return HandlerResult("Ranked временно недоступен.")
        return self._render(self.ranked.calculate(), page)

    def handle_me(self, tg_id: int) -> HandlerResult:
        if not self.features.is_enabled(FeatureFlags.RANKED_PUBLIC):
            return HandlerResult("Ranked временно недоступен.")
        snapshot = self.ranked.calculate()
        user = self.users.get_by_tg_id(tg_id)
        row = next((row for row in snapshot.rows if user is not None and row.user_id == user.id), None)
        if row is None:
            return HandlerResult(
                "Тебя пока нет в публичном рейтинге. Самостоятельно запишись на рейтинговый турнир "
                "через бота, укажи свою колоду после импорта или забронируй колоду Cellar.",
                keyboard=ranked_back_keyboard(0),
            )
        return self._render(
            snapshot,
            (row.position - 1) // LEADERBOARD_PAGE_SIZE,
            highlight_user_id=row.user_id,
        )

    def handle_rules(self, return_page: int = 0) -> HandlerResult:
        return HandlerResult(RANKED_RULES_TEXT, keyboard=ranked_back_keyboard(max(0, return_page)))

    @staticmethod
    def _render(
        snapshot: RankedLeaderboard,
        page: int,
        *,
        highlight_user_id: int | None = None,
    ) -> HandlerResult:
        total_rows = len(snapshot.rows)
        total_pages = max(1, (total_rows + LEADERBOARD_PAGE_SIZE - 1) // LEADERBOARD_PAGE_SIZE)
        page = min(max(0, page), total_pages - 1)
        start = page * LEADERBOARD_PAGE_SIZE
        rows = snapshot.rows[start : start + LEADERBOARD_PAGE_SIZE]
        lines = ["🏆 Moscow Pauper Ranked", "Публичный рейтинг · с 20.06.2026", ""]
        if rows:
            lines.extend(
                f"{'👉 ' if row.user_id == highlight_user_id else ''}{row.position} — {row.name} — {row.score}"
                for row in rows
            )
        else:
            lines.append("Публичный рейтинг пока пуст. Первые игроки появятся после самостоятельной записи.")
        lines.extend(["", f"Страница {page + 1}/{total_pages}"])
        return HandlerResult(
            "\n".join(lines),
            keyboard=ranked_leaderboard_keyboard(
                page,
                total_pages,
                show_me=highlight_user_id is None,
            ),
        )
