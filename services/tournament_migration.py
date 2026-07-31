from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import requests
from pydantic import BaseModel, Field

from core.clubs import ClubIdentity, club_identities
from services.aetherhub_service import AetherhubService
from services.datalens import DataLensService, DataLensTournament
from services.magicoculus import (
    MagicOculusApiError,
    MagicOculusClient,
    MagicOculusPlayerDeck,
    MagicOculusTournament,
)

MigrationStatus = Literal[
    "ready",
    "imported",
    "already_exists",
    "invalid_datalens",
    "missing_aetherhub",
    "ambiguous_aetherhub",
    "aetherhub_error",
    "roster_mismatch",
    "oculus_error",
    "aborted",
]


class TournamentMigrationItem(BaseModel):
    date: date
    club: str
    players: int = Field(ge=0)
    status: MigrationStatus
    aetherhub_url: str | None = None
    magicoculus_tournament_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class TournamentMigrationReport(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    execute: bool
    items: list[TournamentMigrationItem] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            result[item.status] = result.get(item.status, 0) + 1
        return result


class HistoricalTournamentMigrator:
    """Bulk DataLens → AetherHub URL → Magic Oculus migration with per-event isolation."""

    CLUB_ALIASES = {"единорог": "edinorog", "goldfish": "goldfish"}
    LEGACY_AETHERHUB_OWNERS = {
        "edinorog": ("https://aetherhub.com/User/Rog",),
        "goldfish": (),
    }
    KNOWN_AETHERHUB_URLS = {
        ("единорог", date(2025, 3, 22)): "https://aetherhub.com/Tourney/RoundTourney/37996",
    }

    def __init__(
        self,
        datalens: DataLensService,
        aetherhub: AetherhubService,
        oculus: MagicOculusClient,
        *,
        aetherhub_factory: Callable[[], AetherhubService] | None = None,
    ) -> None:
        self._datalens = datalens
        self._aetherhub = aetherhub
        self._oculus = oculus
        self._aetherhub_factory = aetherhub_factory or AetherhubService

    @classmethod
    def _identity(cls, club: str) -> ClubIdentity | None:
        normalized = cls.CLUB_ALIASES.get(club.casefold(), club.casefold())
        return next((row for row in club_identities() if row.name.casefold() == normalized), None)

    @staticmethod
    def _payload(tournament: DataLensTournament, url: str) -> MagicOculusTournament:
        return MagicOculusTournament(
            date=tournament.date,
            club=tournament.club,
            aetherhub_url=url,
            player_decks=[
                MagicOculusPlayerDeck(
                    player=player.player,
                    deck=player.deck,
                    final_place=player.place,
                )
                for player in tournament.players
            ],
        )

    @staticmethod
    def _key(tournament: DataLensTournament) -> tuple[date, str, str]:
        return tournament.date, tournament.club.casefold(), tournament.format.casefold()

    def run(
        self,
        *,
        execute: bool,
        clubs: set[str] | None = None,
        dates: set[date] | None = None,
        on_update: Callable[[TournamentMigrationReport], None] | None = None,
        max_consecutive_system_errors: int = 3,
    ) -> TournamentMigrationReport:
        report = TournamentMigrationReport(started_at=datetime.now(timezone.utc), execute=execute)
        batch = self._datalens.all_tournaments()
        selected_clubs = {club.casefold() for club in clubs} if clubs else {"goldfish", "единорог"}

        for issue in batch.issues:
            if issue.club.casefold() in selected_clubs and (dates is None or issue.date in dates):
                report.items.append(
                    TournamentMigrationItem(
                        date=issue.date,
                        club=issue.club,
                        players=0,
                        status="invalid_datalens",
                        error=issue.message,
                    )
                )

        tournaments = [
            row
            for row in batch.tournaments
            if row.club.casefold() in selected_clubs and (dates is None or row.date in dates)
        ]
        indexes: dict[str, dict[date, list[str]]] = {}
        for tournament in tournaments:
            identity = self._identity(tournament.club)
            if identity and identity.aetherhub_url and identity.name not in indexes:
                club_index = self._aetherhub.tournament_urls_by_date(identity.aetherhub_url, "Pauper")
                for legacy_url in self.LEGACY_AETHERHUB_OWNERS.get(identity.name.casefold(), ()):
                    legacy_index = self._aetherhub.tournament_urls_by_date(legacy_url, "Pauper")
                    for event_date, urls in legacy_index.items():
                        club_index.setdefault(event_date, []).extend(urls)
                indexes[identity.name] = {
                    event_date: list(dict.fromkeys(urls)) for event_date, urls in club_index.items()
                }
        for tournament in tournaments:
            identity = self._identity(tournament.club)
            known_url = self.KNOWN_AETHERHUB_URLS.get((tournament.club.casefold(), tournament.date))
            if identity and known_url:
                indexes.setdefault(identity.name, {}).setdefault(tournament.date, []).append(known_url)

        existing = self._oculus.existing_daily_keys()
        reference_ids: dict[str, tuple[str, str, str]] = {}
        consecutive_system_errors = 0

        for position, tournament in enumerate(tournaments):
            identity = self._identity(tournament.club)
            club_index = indexes.get(identity.name, {}) if identity else {}
            urls = list(club_index.get(tournament.date, []))
            used_adjacent_date = False
            if not urls:
                used_adjacent_date = True
                for offset in (-1, 1):
                    urls.extend(club_index.get(tournament.date + timedelta(days=offset), []))
                urls = list(dict.fromkeys(urls))
            base = dict(date=tournament.date, club=tournament.club, players=len(tournament.players))
            if self._key(tournament) in existing:
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="already_exists",
                        magicoculus_tournament_id=existing[self._key(tournament)],
                    )
                )
                self._notify(report, on_update)
                continue
            if not urls:
                report.items.append(TournamentMigrationItem(**base, status="missing_aetherhub"))
                self._notify(report, on_update)
                continue
            checked: list[tuple[str, int]] = []
            fetch_errors: list[tuple[str, str]] = []
            for candidate_url in urls:
                try:
                    source = self._aetherhub_factory().fetch_tournament(candidate_url)
                    checked.append((candidate_url, len(source.standings or source.players)))
                except Exception as exc:
                    fetch_errors.append((candidate_url, str(exc)))
            matching_urls = [url for url, count in checked if count == len(tournament.players)]
            resolution_warnings = []
            if not used_adjacent_date and len(urls) == 1 and checked:
                selected_url, roster_count = checked[0]
                matching_urls = [selected_url]
                if roster_count != len(tournament.players):
                    resolution_warnings.append(
                        "AETHERHUB_ROSTER_MISMATCH_IGNORED: точный URL выбран по клубу, формату и дате; "
                        f"DataLens={len(tournament.players)}, AetherHub={roster_count}"
                    )
            if len(matching_urls) > 1:
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="ambiguous_aetherhub",
                        error=f"Несколько URL совпали по roster: {matching_urls}",
                    )
                )
                self._notify(report, on_update)
                continue
            if not matching_urls and checked:
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="roster_mismatch",
                        aetherhub_url=checked[0][0] if len(checked) == 1 else None,
                        error=f"DataLens: {len(tournament.players)}, кандидаты AetherHub: {checked}",
                    )
                )
                self._notify(report, on_update)
                continue
            if not matching_urls:
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="aetherhub_error",
                        aetherhub_url=urls[0] if len(urls) == 1 else None,
                        error=f"Не удалось проверить кандидатов: {fetch_errors}",
                    )
                )
                self._notify(report, on_update)
                continue
            url = matching_urls[0]
            if used_adjacent_date:
                resolution_warnings.append(
                    "AETHERHUB_ADJACENT_DATE: URL найден на соседней API-дате и подтверждён точным roster"
                )
            elif len(urls) > 1:
                resolution_warnings.append(
                    "AETHERHUB_ROSTER_DISAMBIGUATED: URL выбран из нескольких кандидатов по точному roster"
                )
            if not execute:
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="ready",
                        aetherhub_url=url,
                        warnings=resolution_warnings,
                    )
                )
                self._notify(report, on_update)
                continue

            try:
                if tournament.club not in reference_ids:
                    reference_ids[tournament.club] = self._oculus.resolve_reference_ids(
                        city="Москва", club=tournament.club, format_name=tournament.format
                    )
                city_id, club_id, format_id = reference_ids[tournament.club]
                result = self._oculus.import_tournament(
                    self._payload(tournament, url),
                    city_id=city_id,
                    club_id=club_id,
                    format_id=format_id,
                )
                existing[self._key(tournament)] = result.tournament_id
                consecutive_system_errors = 0
                report.items.append(
                    TournamentMigrationItem(
                        **base,
                        status="imported",
                        aetherhub_url=url,
                        magicoculus_tournament_id=result.tournament_id,
                        warnings=resolution_warnings
                        + [f"{warning.code}: {warning.message}" for warning in result.warnings],
                    )
                )
            except Exception as exc:
                is_system = isinstance(exc, requests.RequestException) or (
                    isinstance(exc, MagicOculusApiError) and "HTTP 5" in str(exc)
                )
                consecutive_system_errors = consecutive_system_errors + 1 if is_system else 0
                report.items.append(
                    TournamentMigrationItem(**base, status="oculus_error", aetherhub_url=url, error=str(exc))
                )
                if consecutive_system_errors >= max_consecutive_system_errors:
                    for remaining in tournaments[position + 1 :]:
                        report.items.append(
                            TournamentMigrationItem(
                                date=remaining.date,
                                club=remaining.club,
                                players=len(remaining.players),
                                status="aborted",
                                error="Миграция остановлена после повторных системных ошибок Oculus",
                            )
                        )
                    self._notify(report, on_update)
                    break
            self._notify(report, on_update)

        report.finished_at = datetime.now(timezone.utc)
        self._notify(report, on_update)
        return report

    @staticmethod
    def _notify(
        report: TournamentMigrationReport,
        callback: Callable[[TournamentMigrationReport], None] | None,
    ) -> None:
        if callback:
            callback(report)
