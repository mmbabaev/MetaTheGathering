from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from bot.handlers.base import HandlerResult
from core import models
from services import errors
from services.aetherhub_import_service import AetherhubImportService, expected_swiss_rounds
from services.aetherhub_models import AetherhubTournamentData
from services.aetherhub_service import AetherhubService
from services.tournament import TournamentService


@dataclass
class AetherhubFetchResult:
    data: AetherhubTournamentData
    preview_text: str


def tournament_event_date(
    registration_close_at: datetime | None,
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> date:
    """Scheduled event date in the club timezone; stored timestamps are naive UTC."""
    local_timezone = ZoneInfo(timezone_name)
    if registration_close_at is None:
        return (now or datetime.now(local_timezone)).astimezone(local_timezone).date()
    event_at = registration_close_at
    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=timezone.utc)
    return event_at.astimezone(local_timezone).date()


def format_tournament_not_found(club_aetherhub_url: str, event_date: date) -> str:
    """Explain the date mismatch and link the club owner's public content feed."""
    return (
        f"ℹ️ На AetherHub не найден Pauper-турнир клуба за {event_date.strftime('%d.%m.%Y')}.\n\n"
        f"Content Feed клуба:\n{club_aetherhub_url}\n\n"
        "Если нужный турнир уже создан — пришлите ссылку на него."
    )


class AetherhubHandler:
    def __init__(
        self,
        aetherhub_service: AetherhubService,
        import_service: AetherhubImportService | None = None,
        tournament_service: TournamentService | None = None,
    ) -> None:
        self._aetherhub = aetherhub_service
        self._import = import_service
        self._tournament = tournament_service

    def handle_import_prompt(
        self,
        stored_url: str | None,
        club_aetherhub_url: str | None,
        event_date: date,
        tournament_title: str | None = None,
    ) -> AetherhubFetchResult | None:
        """Find tournament URL and fetch preview. Returns None if URL must be provided manually.

        Автопоиск по клубу может найти турнир, который создан на AetherHub, но ещё без раундов
        (0 игроков). Показывать «Игроков: 0» бессмысленно — трактуем как «не найден» и возвращаем
        None, чтобы вызывающий показал список турниров клуба (см. describe_club_tournaments).
        """
        url = stored_url
        if not url and club_aetherhub_url:
            url = self._aetherhub.find_todays_pauper_tournament(club_aetherhub_url, today=event_date)
        if not url:
            return None
        header = "🔄 Обновление AetherHub" if stored_url else "📥 Импорт AetherHub"
        result = self.handle_fetch_preview(url, header, tournament_title=tournament_title)
        if not stored_url and not result.data.players:
            return None
        return result

    def describe_tournament_not_found(self, club_aetherhub_url: str, event_date: date) -> str:
        return format_tournament_not_found(club_aetherhub_url, event_date)

    def handle_fetch_preview(self, url: str, header: str, tournament_title: str | None = None) -> AetherhubFetchResult:
        data = self._aetherhub.fetch_tournament(url)
        return AetherhubFetchResult(
            data=data,
            preview_text=self._build_preview(data, header, tournament_title=tournament_title),
        )

    def handle_confirm_import(self, tournament_id: int, url: str, data: AetherhubTournamentData) -> HandlerResult:
        tournament = self._tournament.db.get(models.Tournament, tournament_id)
        if tournament is not None and tournament.engine_mode == models.TournamentEngineMode.INTERNAL_SWISS:
            return HandlerResult("В этом турнире включён внутренний Swiss; AetherHub не нужен.", is_alert=True)
        try:
            result = self._import.import_tournament(tournament_id, data)
        except errors.TournamentInvalidState as exc:
            return HandlerResult(str(exc), is_alert=True)
        self._tournament.set_aetherhub_url(tournament_id, url)
        expected_rounds = expected_swiss_rounds(result.players_received)
        standings_are_final = (
            result.players_received > 0
            and result.standings_received >= result.players_received
            and result.rounds_received >= expected_rounds
        )
        if result.standings_received:
            standings_status = "финальные" if standings_are_final else "промежуточные"
            standings_line = (
                f"Стендинги: {standings_status} ({result.standings_received} мест, "
                f"{result.rounds_received} из {expected_rounds} раундов)"
            )
        else:
            standings_line = "Стендинги: ещё не опубликованы"

        if result.scores_complete:
            scores_line = "Счёт матчей: опубликован полностью"
        elif standings_are_final:
            scores_line = "Счёт матчей: не опубликован AetherHub (стендинги уже финальные)"
        else:
            scores_line = "Счёт матчей: опубликован не полностью"
        lines = [
            "✅ AetherHub обновлён",
            "",
            f"Участники: получено {result.players_received}",
            f"Новых в боте: {result.registered}",
            f"Уже были: {result.already_registered}",
            "",
            f"Раунды: {result.rounds_received}",
            f"Парингов получено: {result.pairings_received}",
            f"Добавлено или изменено: {result.pairings_changed}",
            "",
            standings_line,
            scores_line,
        ]
        if result.created_names:
            names_str = ", ".join(result.created_names[:5])
            suffix = "…" if len(result.created_names) > 5 else ""
            lines.append(f"Созданы как новые игроки ({len(result.created_names)}): {names_str}{suffix}")
        return HandlerResult(text="\n".join(lines), new_round_numbers=result.new_round_numbers)

    def _build_preview(self, data: AetherhubTournamentData, header: str, tournament_title: str | None = None) -> str:
        rounds_summary = ", ".join(f"R{r.number}: {len(r.pairings) // 2} столов" for r in data.rounds)
        context_lines = []
        if tournament_title:
            context_lines.append(f"Турнир: {tournament_title}")
        context_lines.append(f"AetherHub: {data.url}")
        preview = (
            f"{header}\n" + "\n".join(context_lines) + "\n\n"
            f"Игроков: {len(data.players)}\n"
            f"Раунды: {rounds_summary}\n\n"
            f"Первые 5 игроков:\n" + "\n".join(f"  • {p}" for p in data.players[:5])
        )
        if len(data.players) > 5:
            preview += f"\n  …ещё {len(data.players) - 5}"
        return preview
