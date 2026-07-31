"""Подготовка одного турнира MetaGatherer к импорту в Magic Oculus."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import models
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


class MagicOculusTournamentCollector:
    """Собирает импортируемый дейлик из уже проверенных данных БД бота."""

    def __init__(self, db: Session) -> None:
        self.db = db

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
        if not tournament.aetherhub_url:
            raise MagicOculusCollectionError(f"У турнира #{tournament_id} нет AetherHub URL")

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

        event_date = (tournament.started_at or tournament.created_at).date()
        try:
            return MagicOculusTournament(
                source_tournament_id=tournament.id,
                date=event_date,
                club=tournament.club,
                aetherhub_url=tournament.aetherhub_url,
                player_decks=rows,
            )
        except ValueError as exc:
            raise MagicOculusCollectionError(str(exc)) from exc
