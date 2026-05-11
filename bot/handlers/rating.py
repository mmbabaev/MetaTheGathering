from bot.handlers.base import HandlerResult
from bot.messages import format_participant_name
from services.rating import RatingService
from services.tournament import TournamentService
from services.user import UserService


class RatingHandler:
    def __init__(self, svc: TournamentService, user_svc: UserService) -> None:
        self.svc = svc
        self.user_svc = user_svc

    def handle_social_rating(self, tg_id: int) -> HandlerResult:
        """Топ-10 игроков по количеству внесённых колод."""
        contributors = RatingService(self.svc.db).top_deck_contributors(limit=10)
        if not contributors:
            return HandlerResult("Пока никто не внёс ни одной колоды.")
        lines = ["🏆 Социальный рейтинг — кто больше всех внёс колод:\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (user, cnt) in enumerate(contributors):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            name = format_participant_name(user.first_name, user.last_name) or f"id{user.tg_id}"
            username_part = f" (@{user.username})" if user.username else ""
            noun = _deck_noun(cnt)
            lines.append(f"{prefix} {name}{username_part} — {cnt} {noun}")
        return HandlerResult("\n".join(lines))


def _deck_noun(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "колод"
    rem = n % 10
    if rem == 1:
        return "колода"
    if 2 <= rem <= 4:
        return "колоды"
    return "колод"
