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
        """Find tournament URL and fetch preview. Returns None if URL must be provided manually.

        Автопоиск по клубу может найти турнир, который создан на AetherHub, но ещё без раундов
        (0 игроков). Показывать «Игроков: 0» бессмысленно — трактуем как «не найден» и возвращаем
        None, чтобы вызывающий показал список турниров клуба (см. describe_club_tournaments).
        """
        url = stored_url
        if not url and club_aetherhub_url:
            url = self._aetherhub.find_todays_pauper_tournament(club_aetherhub_url)
        if not url:
            return None
        header = "🔄 Обновление AetherHub" if stored_url else "📥 Импорт AetherHub"
        result = self.handle_fetch_preview(url, header)
        if not stored_url and not result.data.players:
            return None
        return result

    def describe_club_tournaments(self, club_aetherhub_url: str) -> str:
        """Сообщение «сегодняшний турнир не найден» + список турниров со страницы клуба.

        Показываем админу, что именно вернул AetherHub для клуба, когда сегодняшний паупер-турнир
        найти не удалось (ещё не создан / создан пустым) — чтобы было видно, чего ждать, и можно
        было при необходимости прислать ссылку вручную.
        """
        header = "❌ Сегодняшний паупер-турнир на AetherHub найти не удалось."
        try:
            links = self._aetherhub.fetch_club_tournaments(club_aetherhub_url)
        except Exception:
            return header
        if not links:
            return f"{header}\nНа странице клуба турниров не видно."
        lines = [header, "", "Что сейчас на странице клуба:"]
        for link in links[:8]:
            date_str = link.date.strftime("%d.%m") if link.date else "—"
            mark = "🎲" if link.is_pauper else "▫️"
            lines.append(f"{mark} {date_str} — {link.name}")
        lines.append("")
        lines.append("Если нужный турнир уже создан — пришлите ссылку на него.")
        return "\n".join(lines)

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
        return HandlerResult(text="\n".join(lines), new_round_numbers=result.new_round_numbers)

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
