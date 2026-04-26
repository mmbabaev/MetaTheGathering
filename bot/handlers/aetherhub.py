from __future__ import annotations

from dataclasses import dataclass

from bot.handlers.base import HandlerResult
from services.aetherhub_import_service import AetherhubImportService
from services.aetherhub_models import AetherhubTournamentData
from services.aetherhub_service import AetherhubService
from services.tournament import TournamentService


@dataclass
class AetherhubFetchResult:
    data: AetherhubTournamentData
    preview_text: str


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
        self, stored_url: str | None, club_aetherhub_url: str | None
    ) -> AetherhubFetchResult | None:
        """Find tournament URL and fetch preview. Returns None if URL must be provided manually."""
        url = stored_url
        if not url and club_aetherhub_url:
            url = self._aetherhub.find_todays_pauper_tournament(club_aetherhub_url)
        if not url:
            return None
        header = "🔄 Обновление AetherHub" if stored_url else "📥 Импорт AetherHub"
        return self.handle_fetch_preview(url, header)

    def handle_fetch_preview(self, url: str, header: str) -> AetherhubFetchResult:
        data = self._aetherhub.fetch_tournament(url)
        return AetherhubFetchResult(data=data, preview_text=self._build_preview(data, header))

    def handle_confirm_import(self, tournament_id: int, url: str, data: AetherhubTournamentData) -> HandlerResult:
        result = self._import.import_tournament(tournament_id, data)
        self._tournament.set_aetherhub_url(tournament_id, url)
        lines = [
            "✅ Импорт завершён",
            f"Зарегистрировано новых: {result.registered}",
            f"Уже были: {result.already_registered}",
            f"Паринги сохранены: {result.pairings_saved}",
        ]
        if result.created_names:
            names_str = ", ".join(result.created_names[:5])
            suffix = "…" if len(result.created_names) > 5 else ""
            lines.append(f"Созданы как новые игроки ({len(result.created_names)}): {names_str}{suffix}")
        return HandlerResult(text="\n".join(lines))

    def _build_preview(self, data: AetherhubTournamentData, header: str) -> str:
        rounds_summary = ", ".join(f"R{r.number}: {len(r.pairings) // 2} столов" for r in data.rounds)
        preview = (
            f"{header}\n\n"
            f"Игроков: {len(data.players)}\n"
            f"Раунды: {rounds_summary}\n\n"
            f"Первые 5 игроков:\n" + "\n".join(f"  • {p}" for p in data.players[:5])
        )
        if len(data.players) > 5:
            preview += f"\n  …ещё {len(data.players) - 5}"
        return preview
