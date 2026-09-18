"""Public presentation of Russian players in Endstep Pauper Ranked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from zoneinfo import ZoneInfo

from bot.handlers.base import HandlerResult
from bot.keyboards import endstep_ru_back_keyboard, endstep_ru_leaderboard_keyboard
from core.config import settings
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardService
from services.user import UserService

ENDSTEP_RU_PAGE_SIZE = 10
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class EndstepRuLeaderboardLoad:
    result: HandlerResult
    snapshot: EndstepRuLeaderboard | None


class EndstepRuLeaderboardHandler:
    def __init__(
        self,
        service: EndstepRuLeaderboardService | None = None,
        users: UserService | None = None,
    ) -> None:
        self.service = service
        self.users = users

    def load(self, tg_id: int, page: int = 0) -> EndstepRuLeaderboardLoad:
        if self.service is None:
            raise RuntimeError("EndstepRuLeaderboardService is required to load a snapshot")
        snapshot = self.service.latest()
        if snapshot is None:
            return EndstepRuLeaderboardLoad(
                HandlerResult(
                    "Endstep RU leaderboard ещё не обновлялся. Фоновый worker создаст первый снимок автоматически.",
                    keyboard=endstep_ru_leaderboard_keyboard(0, 1),
                ),
                None,
            )
        return EndstepRuLeaderboardLoad(self.render(tg_id, snapshot, page), snapshot)

    def load_me(self, tg_id: int) -> EndstepRuLeaderboardLoad:
        if self.service is None or self.users is None:
            raise RuntimeError("Endstep leaderboard and user services are required to find a player")
        snapshot = self.service.latest()
        if snapshot is None:
            return self.load(tg_id)

        user = self.users.get_by_tg_id(tg_id)
        row = next((row for row in snapshot.rows if user is not None and row.user_id == user.id), None)
        if row is None:
            return EndstepRuLeaderboardLoad(
                HandlerResult(
                    "Тебя пока нет в Endstep RU рейтинге. Укажи точный Endstep-ник "
                    "в настройках бота и сыграй турнир Endstep-ru. Если всё уже заполнено, "
                    "дождись следующего обновления рейтинга.",
                    keyboard=endstep_ru_back_keyboard(),
                ),
                snapshot,
            )
        page = (row.position - 1) // ENDSTEP_RU_PAGE_SIZE
        return EndstepRuLeaderboardLoad(
            self.render(tg_id, snapshot, page, highlight_user_id=row.user_id),
            snapshot,
        )

    def render(
        self,
        tg_id: int,
        snapshot: EndstepRuLeaderboard,
        page: int = 0,
        *,
        highlight_user_id: int | None = None,
    ) -> HandlerResult:
        total_rows = len(snapshot.rows)
        total_pages = max(1, (total_rows + ENDSTEP_RU_PAGE_SIZE - 1) // ENDSTEP_RU_PAGE_SIZE)
        page = min(max(0, page), total_pages - 1)
        start = page * ENDSTEP_RU_PAGE_SIZE
        rows = snapshot.rows[start : start + ENDSTEP_RU_PAGE_SIZE]
        generated_at = snapshot.generated_at.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ)
        lines = [
            "🏆 Endstep Pauper Ranked — RU",
            f"Обновлено {generated_at.strftime('%d.%m.%Y %H:%M')} МСК · игроков: {total_rows}",
            "",
        ]
        if rows:
            for row in rows:
                marker = "👉 " if row.user_id == highlight_user_id else ""
                site_place = f"#{row.site_rank}" if row.site_rank is not None else "—*"
                lines.extend(
                    [
                        f"{marker}<b>{row.position}. {_escape(row.username)}</b>",
                        f"    сайт {site_place} · {row.rating} (RD {row.rd}) · {row.wins}–{row.losses}–{row.draws}",
                    ]
                )
            lines.extend(["", "Формат: победы–поражения–ничьи. RD — отклонение рейтинга."])
            if any(row.provisional for row in rows):
                lines.append("* provisional — Endstep ещё не назначил место на сайте.")
        elif snapshot.candidate_count == 0:
            lines.append("В турнирах Endstep-ru пока нет игроков с заполненным Endstep-ником.")
        else:
            lines.append("Ни один указанный Endstep-ник пока не найден в Pauper leaderboard.")

        if settings.OWNER_CHAT_ID is not None and tg_id == settings.OWNER_CHAT_ID:
            if snapshot.missing_usernames:
                lines.extend(["", f"Не найдены: {_visible_usernames(snapshot.missing_usernames)}"])
            if snapshot.ambiguous_usernames:
                lines.extend(
                    [
                        "",
                        f"Несколько аккаунтов с этим ником: {_visible_usernames(snapshot.ambiguous_usernames)}",
                    ]
                )

        lines.extend(["", f"Страница {page + 1}/{total_pages}"])
        return HandlerResult(
            "\n".join(lines),
            keyboard=endstep_ru_leaderboard_keyboard(
                page,
                total_pages,
                show_me=highlight_user_id is None,
            ),
            parse_mode="HTML",
        )


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _visible_usernames(usernames: tuple[str, ...]) -> str:
    visible = [name if len(name) <= 40 else f"{name[:39]}…" for name in usernames[:5]]
    suffix = f" и ещё {len(usernames) - len(visible)}" if len(usernames) > len(visible) else ""
    return f"{_escape(', '.join(visible))}{suffix}"
