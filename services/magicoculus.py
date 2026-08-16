"""Подготовка одного турнира MetaGatherer к импорту в Magic Oculus."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import models
from core.clubs import club_identities
from services.aetherhub_service import AetherhubService
from services.names import format_participant_name, is_single_word_name_typo


def _roster_name_key(name: str) -> tuple[str, ...]:
    """Order-independent full-name key shared by MetaGatherer and AetherHub rosters."""
    return tuple(sorted(name.strip().casefold().replace("ё", "е").split()))


def _matched_roster_indexes(metagatherer_names: list[str], aetherhub_names: list[str]) -> set[int]:
    """MetaGatherer row indexes matched exactly or by one unambiguous one-letter typo."""
    matched_meta: set[int] = set()
    matched_aetherhub: set[int] = set()

    meta_by_key: dict[tuple[str, ...], list[int]] = {}
    source_by_key: dict[tuple[str, ...], list[int]] = {}
    for index, name in enumerate(metagatherer_names):
        meta_by_key.setdefault(_roster_name_key(name), []).append(index)
    for index, name in enumerate(aetherhub_names):
        source_by_key.setdefault(_roster_name_key(name), []).append(index)
    for key in meta_by_key.keys() & source_by_key.keys():
        meta_indexes = meta_by_key[key]
        source_indexes = source_by_key[key]
        if len(meta_indexes) == len(source_indexes) == 1:
            matched_meta.add(meta_indexes[0])
            matched_aetherhub.add(source_indexes[0])

    unmatched_meta = set(range(len(metagatherer_names))) - matched_meta
    unmatched_source = set(range(len(aetherhub_names))) - matched_aetherhub
    meta_candidates = {
        meta_index: {
            source_index
            for source_index in unmatched_source
            if is_single_word_name_typo(metagatherer_names[meta_index], aetherhub_names[source_index])
        }
        for meta_index in unmatched_meta
    }
    source_candidates = {
        source_index: {
            meta_index
            for meta_index in unmatched_meta
            if is_single_word_name_typo(metagatherer_names[meta_index], aetherhub_names[source_index])
        }
        for source_index in unmatched_source
    }
    for meta_index, candidates in meta_candidates.items():
        if len(candidates) != 1:
            continue
        source_index = next(iter(candidates))
        if source_candidates[source_index] == {meta_index}:
            matched_meta.add(meta_index)
    return matched_meta


class MagicOculusPlayerDeck(BaseModel):
    model_config = ConfigDict(frozen=True)

    player: str = Field(min_length=1)
    deck: str = Field(min_length=1)
    final_place: int | None = Field(default=None, ge=1)


class MagicOculusTournament(BaseModel):
    """Нормализованные данные одного дейлика до подстановки ID справочников."""

    model_config = ConfigDict(frozen=True)

    source_tournament_id: int | None = Field(default=None, ge=1)
    date: date
    club: str = Field(min_length=1)
    format: str = "Pauper"
    tournament_type: str = "daily"
    aetherhub_url: HttpUrl
    player_decks: list[MagicOculusPlayerDeck] = Field(min_length=1)

    @property
    def player_decks_text(self) -> str:
        return "\n".join(f"{row.player} - {row.deck}" for row in self.player_decks)

    @property
    def positional_player_decks_text(self) -> str:
        """Колоды по местам AetherHub; имена не участвуют в matching Magic Oculus."""
        places = [row.final_place for row in self.player_decks]
        expected = list(range(1, len(self.player_decks) + 1))
        if places != expected:
            raise MagicOculusCollectionError(
                f"Для позиционного импорта места должны идти 1..{len(self.player_decks)}, получено: {places}"
            )
        return "\n".join(row.deck for row in self.player_decks)


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

    def collect(self, tournament_id: int, *, validate_aetherhub: bool = False) -> MagicOculusTournament:
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
        aetherhub_players = self._fetch_aetherhub_players(aetherhub_url) if validate_aetherhub else None

        rows: list[MagicOculusPlayerDeck] = []
        missing_names: list[str] = []
        missing_decks: list[str] = []
        seen_names: set[str] = set()
        participants = sorted(
            tournament.participants,
            key=lambda row: (row.final_place is None, row.final_place or 0, row.id),
        )
        participant_names = [
            format_participant_name(participant.user.first_name, participant.user.last_name).strip()
            for participant in participants
        ]
        matched_participants = (
            _matched_roster_indexes(participant_names, aetherhub_players)
            if aetherhub_players is not None
            else None
        )
        for index, participant in enumerate(participants):
            player = participant_names[index]
            if not player:
                missing_names.append(f"participant:{participant.id}")
                continue
            # Players who registered but did not actually play are absent from the authoritative
            # AetherHub roster and must not block/export into Magic Oculus.
            if matched_participants is not None and index not in matched_participants:
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
            result = MagicOculusTournament(
                source_tournament_id=tournament.id,
                date=event_date,
                club=tournament.club,
                aetherhub_url=aetherhub_url,
                player_decks=rows,
            )
        except ValueError as exc:
            raise MagicOculusCollectionError(str(exc)) from exc
        if validate_aetherhub:
            self.validate_aetherhub_players(result, aetherhub_players=aetherhub_players)
        return result

    def _fetch_aetherhub_players(self, url: str) -> list[str]:
        try:
            source = self._aetherhub.fetch_tournament(url)
        except Exception as exc:
            raise MagicOculusCollectionError(f"Не удалось проверить состав AetherHub: {exc}") from exc
        aetherhub_players = source.standings or source.players
        if not aetherhub_players:
            raise MagicOculusCollectionError("AetherHub не вернул ни standings, ни игроков")
        return [name for name in aetherhub_players if name.upper() != "BYE"]

    def validate_aetherhub_players(
        self,
        tournament: MagicOculusTournament,
        *,
        aetherhub_players: list[str] | None = None,
    ) -> None:
        players = aetherhub_players or self._fetch_aetherhub_players(str(tournament.aetherhub_url))
        metagatherer_names = [row.player for row in tournament.player_decks]
        matched = _matched_roster_indexes(metagatherer_names, players)
        if len(matched) != len(players) or len(players) != len(tournament.player_decks):
            raise MagicOculusCollectionError(
                f"Состав не совпадает: в MetaGatherer {len(tournament.player_decks)} колод, "
                f"в AetherHub {len(players)} игроков"
            )


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

    def existing_daily_keys(self) -> dict[tuple[date, str, str], int]:
        """Index existing dailies by date, club name and format name."""
        page = 1
        result: dict[tuple[date, str, str], int] = {}
        while True:
            body = self._get_json(f"/api/v1/tournaments?page={page}")
            rows = body.get("results", [])
            for row in rows:
                if row.get("type") != "daily":
                    continue
                try:
                    key = (
                        date.fromisoformat(row["date"]),
                        row["club"]["name"].casefold(),
                        row["format"]["name"].casefold(),
                    )
                    result[key] = int(row["id"])
                except (KeyError, TypeError, ValueError):
                    continue
            if not body.get("next") or not rows:
                break
            page += 1
        return result

    @staticmethod
    def _find_reference(rows: list[MagicOculusReference], name: str, kind: str) -> MagicOculusReference:
        matches = [row for row in rows if row.name.casefold() == name.casefold()]
        if len(matches) != 1:
            raise MagicOculusApiError(f'{kind} "{name}": найдено {len(matches)} совпадений в справочнике')
        return matches[0]

    def resolve_reference_ids(self, *, city: str, club: str, format_name: str) -> tuple[str, str, str]:
        city_ref = self._find_reference(self.cities(), city, "Город")
        magicoculus_club = {"edinorog": "Единорог"}.get(club.casefold(), club)
        club_ref = self._find_reference(self.clubs(city_ref.id), magicoculus_club, "Клуб")
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
            # Позиционный режим намеренно не использует имена AetherHub: источник колод и мест — бот.
            "playerDecksText": (None, tournament.positional_player_decks_text),
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


class MagicOculusImporter:
    """Оркестратор one-shot импорта с durable guard до сетевого POST."""

    def __init__(self, db: Session, client: MagicOculusClient) -> None:
        self.db = db
        self.client = client

    def import_once(self, tournament: MagicOculusTournament, *, city: str) -> MagicOculusImportResult:
        existing = (
            self.db.execute(
                select(models.MagicOculusImport).where(
                    (models.MagicOculusImport.tournament_id == tournament.source_tournament_id)
                    | (models.MagicOculusImport.aetherhub_url == str(tournament.aetherhub_url))
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise MagicOculusApiError(
                f"Импорт уже зафиксирован в журнале #{existing.id} со статусом {existing.status}; "
                "автоматический повтор запрещён"
            )

        journal = models.MagicOculusImport(
            tournament_id=tournament.source_tournament_id,
            aetherhub_url=str(tournament.aetherhub_url),
            status="pending",
        )
        self.db.add(journal)
        self.db.commit()  # guard обязан попасть в БД до запроса, который мог фактически сработать перед timeout

        try:
            city_id, club_id, format_id = self.client.resolve_reference_ids(
                city=city,
                club=tournament.club,
                format_name=tournament.format,
            )
            result = self.client.import_tournament(
                tournament,
                city_id=city_id,
                club_id=club_id,
                format_id=format_id,
            )
        except Exception as exc:
            journal.status = "error"
            journal.error_json = json.dumps({"type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)
            self.db.commit()
            raise

        journal.status = "imported"
        journal.magicoculus_tournament_id = result.tournament_id
        journal.warnings_json = json.dumps(
            [warning.model_dump(mode="json") for warning in result.warnings], ensure_ascii=False
        )
        journal.error_json = None
        journal.imported_at = models.utc_now()
        self.db.commit()
        return result
