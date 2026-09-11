"""Owner-only presentation of Russian players in Endstep Pauper Ranked."""

from __future__ import annotations

from dataclasses import dataclass

from bot.handlers.base import HandlerResult
from bot.keyboards import endstep_ru_leaderboard_keyboard
from core.config import settings
from services.endstep import EndstepApiError
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService

ENDSTEP_RU_PAGE_SIZE = 10
ENDSTEP_RU_NOT_OWNER = "Эта команда доступна только владельцу бота."


@dataclass(frozen=True)
class EndstepRuLeaderboardLoad:
    result: HandlerResult
    snapshot: EndstepRuLeaderboard | None


class EndstepRuLeaderboardHandler:
    def __init__(self, service: EndstepRuLeaderboardService | None = None) -> None:
        self.service = service

    @staticmethod
    def _is_owner(tg_id: int) -> bool:
        return settings.OWNER_CHAT_ID is not None and tg_id == settings.OWNER_CHAT_ID

    def load(self, tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
        if not self._is_owner(tg_id):
            return EndstepRuLeaderboardLoad(HandlerResult(ENDSTEP_RU_NOT_OWNER, is_alert=True), None)
        if self.service is None:
            raise RuntimeError("EndstepRuLeaderboardService is required to load a snapshot")
        try:
            snapshot = self.service.calculate()
        except EndstepApiError as exc:
            return EndstepRuLeaderboardLoad(
                HandlerResult(
                    f"Не удалось загрузить Endstep leaderboard: {exc}",
                    keyboard=endstep_ru_leaderboard_keyboard(0, 1),
                ),
                None,
            )
        return EndstepRuLeaderboardLoad(self.render(tg_id, snapshot, page), snapshot)

    def render(self, tg_id: int, snapshot: EndstepRuLeaderboard, page: int = 0) -> HandlerResult:
        if not self._is_owner(tg_id):
            return HandlerResult(ENDSTEP_RU_NOT_OWNER, is_alert=True)

        total_rows = len(snapshot.rows)
        total_pages = max(1, (total_rows + ENDSTEP_RU_PAGE_SIZE - 1) // ENDSTEP_RU_PAGE_SIZE)
        page = min(max(0, page), total_pages - 1)
        start = page * ENDSTEP_RU_PAGE_SIZE
        rows = snapshot.rows[start : start + ENDSTEP_RU_PAGE_SIZE]
        lines = [
            "🏆 Endstep Pauper — RU",
            f"Текущий сезон · найдено {total_rows} из {snapshot.candidate_count}",
            "",
        ]
        if rows:
            for row in rows:
                site_place = f"#{row.site_rank}" if row.site_rank is not None else "без места"
                provisional = " · provisional" if row.provisional else ""
                lines.append(
                    f"{row.position}. {row.username} — сайт {site_place} · "
                    f"{row.rating} ±{row.rd} · {row.wins}–{row.losses}–{row.draws}{provisional}"
                )
        elif snapshot.candidate_count == 0:
            lines.append("В турнирах Endstep-ru пока нет игроков с заполненным Endstep-ником.")
        else:
            lines.append("Ни один указанный Endstep-ник пока не найден в Pauper leaderboard.")

        if snapshot.missing_usernames:
            visible = [name if len(name) <= 40 else f"{name[:39]}…" for name in snapshot.missing_usernames[:5]]
            suffix = (
                f" и ещё {len(snapshot.missing_usernames) - len(visible)}"
                if len(snapshot.missing_usernames) > len(visible)
                else ""
            )
            lines.extend(["", f"Не найдены: {', '.join(visible)}{suffix}"])
        if snapshot.ambiguous_usernames:
            visible = [name if len(name) <= 40 else f"{name[:39]}…" for name in snapshot.ambiguous_usernames[:5]]
            suffix = (
                f" и ещё {len(snapshot.ambiguous_usernames) - len(visible)}"
                if len(snapshot.ambiguous_usernames) > len(visible)
                else ""
            )
            lines.extend(["", f"Несколько аккаунтов с этим ником: {', '.join(visible)}{suffix}"])
        lines.extend(["", f"Страница {page + 1}/{total_pages}"])
        return HandlerResult(
            "\n".join(lines),
            keyboard=endstep_ru_leaderboard_keyboard(page, total_pages),
        )
