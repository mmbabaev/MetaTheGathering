"""Pure admin-only handler for the Moscow Pauper preseason leaderboard."""

from bot.handlers.base import HandlerResult
from bot.messages import NOT_ADMIN
from services.ranked import RankedPreseasonService
from services.user import UserService


class RankedPreseasonHandler:
    def __init__(self, ranked: RankedPreseasonService, users: UserService) -> None:
        self.ranked = ranked
        self.users = users

    def handle(self, tg_id: int) -> HandlerResult:
        if not self.users.is_admin(tg_id):
            return HandlerResult(NOT_ADMIN)

        snapshot = self.ranked.calculate()
        top = snapshot.top(10)
        if not top:
            return HandlerResult("Пока нет откалиброванных игроков для preseason-рейтинга.")

        lines = [
            "🏆 Moscow Pauper Ranked · preseason",
            "20.06–19.09.2026 · только данные бота",
            "",
        ]
        medals = ["🥇", "🥈", "🥉"]
        for index, entry in enumerate(top):
            prefix = medals[index] if index < len(medals) else f"{index + 1}."
            linked = " ✅" if entry.telegram_linked else ""
            lines.append(f"{prefix} {entry.name}{linked} — {entry.ranked_score}")
            lines.append(
                f"   {entry.tournaments} турн. · {entry.matches} матч. · "
                f"{entry.wins}–{entry.draws}–{entry.losses} · R {entry.rating:.0f} / RD {entry.deviation:.0f}"
            )

        quality = snapshot.quality
        lines.extend(
            [
                "",
                f"Матчи: {quality.matches_included}; турниры: {quality.tournaments_included}.",
                (
                    "Исключено: "
                    f"дубли {quality.excluded_duplicate_source}, "
                    f"без парингов {quality.excluded_no_pairings}, "
                    f"неполные {quality.excluded_incomplete}, "
                    f"незакрытые {quality.excluded_not_closed}, "
                    f"identity {quality.unresolved_matches}, "
                    f"противоречия {quality.inconsistent_matches}."
                ),
                "✅ — игрок связан с Telegram. Рейтинг видит только администратор.",
                f"Алгоритм: {snapshot.algorithm_version}; калибровка: ≥3 турниров и ≥10 матчей.",
            ]
        )
        return HandlerResult("\n".join(lines))
