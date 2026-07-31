"""Подготовка одного турнира MetaGatherer к импорту в Magic Oculus."""

from __future__ import annotations

from datetime import date
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import models
from core.clubs import club_identities
from services.aetherhub_service import AetherhubService
from services.names import format_participant_name


class MagicOculusPlayerDeck(BaseModel):
    model_config = ConfigDict(frozen=True)

    player: str = Field(min_length=1)
    deck: str = Field(min_length=1)
    final_place: int | None = Field(default=None, ge=1)


class MagicOculusTournament(BaseModel):
    """Нормализованные данные одного дейлика до подстановки ID справочников."""

    model_config = ConfigDict(frozen=True)

    source_tournament_id: int = Field(ge=1)
    date: date
    club: str = Field(min_length=1)
    format: str = "Pauper"
    tournament_type: str = "daily"
    aetherhub_url: HttpUrl
    player_decks: list[MagicOculusPlayerDeck] = Field(min_length=1)

    @property
    def player_decks_text(self) -> str:
        return "\n".join(f"{row.player} - {row.deck}" for row in self.player_decks)


class MagicOculusCollectionError(ValueError):
    pass


class MagicOculusApiError(RuntimeError):
    pass


class MagicOculusReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str


class MagicOculusFeedback(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    code: str
    message: str
    source: str | None = None


class MagicOculusImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tournament_id: int
    warnings: list[MagicOculusFeedback] = Field(default_factory=list)
    detail: dict[str, Any]


class MagicOculusTournamentCollector:
    """Собирает импортируемый дейлик из уже проверенных данных БД бота."""

    def __init__(self, db: Session, aetherhub_service: AetherhubService | None = None) -> None:
        self.db = db
        self._aetherhub = aetherhub_service or AetherhubService()

    def _resolve_aetherhub_url(self, tournament: models.Tournament, event_date: date) -> str:
        if tournament.aetherhub_url:
            return tournament.aetherhub_url
        identity = next(
            (row for row in club_identities() if row.name.casefold() == (tournament.club or "").casefold()),
            None,
        )
        if identity is None or not identity.aetherhub_url:
            raise MagicOculusCollectionError(f'Для клуба "{tournament.club}" не настроена страница AetherHub')
        try:
            url = self._aetherhub.find_todays_pauper_tournament(identity.aetherhub_url, today=event_date)
        except Exception as exc:
            raise MagicOculusCollectionError(
                f"Не удалось найти AetherHub URL для {tournament.club} за {event_date.isoformat()}: {exc}"
            ) from exc
        if not url:
            raise MagicOculusCollectionError(
                f"На странице клуба {tournament.club} не найден Pauper-турнир за {event_date.isoformat()}"
            )
        return url

    def collect(self, tournament_id: int) -> MagicOculusTournament:
        tournament = (
            self.db.execute(
                select(models.Tournament)
                .where(models.Tournament.id == tournament_id)
                .options(
                    joinedload(models.Tournament.participants).joinedload(models.Participant.user),
                    joinedload(models.Tournament.participants).joinedload(models.Participant.archetype),
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if tournament is None:
            raise MagicOculusCollectionError(f"Турнир #{tournament_id} не найден")
        if not tournament.club:
            raise MagicOculusCollectionError(f"У турнира #{tournament_id} не указан клуб")
        event_date = (tournament.started_at or tournament.created_at).date()
        aetherhub_url = self._resolve_aetherhub_url(tournament, event_date)

        rows: list[MagicOculusPlayerDeck] = []
        missing_names: list[str] = []
        missing_decks: list[str] = []
        seen_names: set[str] = set()
        participants = sorted(
            tournament.participants,
            key=lambda row: (row.final_place is None, row.final_place or 0, row.id),
        )
        for participant in participants:
            player = format_participant_name(participant.user.first_name, participant.user.last_name).strip()
            if not player:
                missing_names.append(f"participant:{participant.id}")
                continue
            if player.casefold() in seen_names:
                raise MagicOculusCollectionError(f'Имя игрока "{player}" встречается несколько раз')
            seen_names.add(player.casefold())
            if participant.archetype is None or not participant.archetype.name.strip():
                missing_decks.append(player)
                continue
            rows.append(
                MagicOculusPlayerDeck(
                    player=player,
                    deck=participant.archetype.name.strip(),
                    final_place=participant.final_place,
                )
            )

        problems: list[str] = []
        if missing_names:
            problems.append("нет имени: " + ", ".join(missing_names))
        if missing_decks:
            problems.append("нет колоды: " + ", ".join(missing_decks))
        if problems:
            raise MagicOculusCollectionError("; ".join(problems))
        if not rows:
            raise MagicOculusCollectionError(f"У турнира #{tournament_id} нет участников")

        try:
            return MagicOculusTournament(
                source_tournament_id=tournament.id,
                date=event_date,
                club=tournament.club,
                aetherhub_url=aetherhub_url,
                player_decks=rows,
            )
        except ValueError as exc:
            raise MagicOculusCollectionError(str(exc)) from exc


class MagicOculusClient:
    """HTTP-клиент публичного daily import API; transport инжектируется для тестов."""

    def __init__(
        self,
        base_url: str,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def _get_json(self, path: str) -> Any:
        response = self._session.get(f"{self._base_url}{path}", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def cities(self) -> list[MagicOculusReference]:
        return [MagicOculusReference.model_validate(row) for row in self._get_json("/api/v1/cities")]

    def clubs(self, city_id: str) -> list[MagicOculusReference]:
        rows = self._get_json(f"/api/v1/cities/{city_id}/clubs")
        return [MagicOculusReference.model_validate(row) for row in rows]

    def formats(self) -> list[MagicOculusReference]:
        return [MagicOculusReference.model_validate(row) for row in self._get_json("/api/v1/formats")]

    @staticmethod
    def _find_reference(rows: list[MagicOculusReference], name: str, kind: str) -> MagicOculusReference:
        matches = [row for row in rows if row.name.casefold() == name.casefold()]
        if len(matches) != 1:
            raise MagicOculusApiError(f'{kind} "{name}": найдено {len(matches)} совпадений в справочнике')
        return matches[0]

    def resolve_reference_ids(self, *, city: str, club: str, format_name: str) -> tuple[str, str, str]:
        city_ref = self._find_reference(self.cities(), city, "Город")
        club_ref = self._find_reference(self.clubs(city_ref.id), club, "Клуб")
        format_ref = self._find_reference(self.formats(), format_name, "Формат")
        return city_ref.id, club_ref.id, format_ref.id

    def import_tournament(
        self,
        tournament: MagicOculusTournament,
        *,
        city_id: str,
        club_id: str,
        format_id: str,
    ) -> MagicOculusImportResult:
        fields = {
            "date": (None, tournament.date.isoformat()),
            "cityId": (None, city_id),
            "clubId": (None, club_id),
            "tournamentType": (None, tournament.tournament_type),
            "formatId": (None, format_id),
            "aetherhubUrl": (None, str(tournament.aetherhub_url)),
            "playerDecksText": (None, tournament.player_decks_text),
        }
        response = self._session.post(
            f"{self._base_url}/api/v1/admin/tournaments/import",
            files=fields,
            timeout=self._timeout,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise MagicOculusApiError(f"Magic Oculus вернул не-JSON (HTTP {response.status_code})") from exc
        if not response.ok or body.get("success") is not True:
            feedback = body.get("errors") or []
            details = "; ".join(f"{row.get('code', 'UNKNOWN')}: {row.get('message', '')}" for row in feedback)
            raise MagicOculusApiError(
                f"Импорт отклонён (HTTP {response.status_code})" + (f": {details}" if details else "")
            )
        raw_tournament = body.get("tournament") or {}
        tournament_id = raw_tournament.get("id")
        if not isinstance(tournament_id, int):
            raise MagicOculusApiError("Успешный ответ не содержит числовой tournament.id")
        warnings = [MagicOculusFeedback.model_validate(row) for row in body.get("warnings") or []]
        detail = self._get_json(f"/api/v1/tournaments/{tournament_id}")
        return MagicOculusImportResult(tournament_id=tournament_id, warnings=warnings, detail=detail)
