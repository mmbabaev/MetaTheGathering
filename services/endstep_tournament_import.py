"""Import Endstep CSV exports into a local read-only tournament snapshot."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core import models


class EndstepImportError(ValueError):
    """The supplied Endstep exports do not match the supported CSV contract."""


@dataclass(frozen=True)
class EndstepImportSummary:
    tournament_id: int
    standings: int
    pairings: int
    deck_cards: int
    matched_users: int


def _read_csv(path: str | Path, required_columns: set[str]) -> list[dict[str, str]]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = set(reader.fieldnames or ())
            missing = required_columns - columns
            if missing:
                raise EndstepImportError(f"{path.name}: отсутствуют колонки: {', '.join(sorted(missing))}")
            return [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    except OSError as exc:
        raise EndstepImportError(f"Не удалось прочитать {path}") from exc


def _required_int(value: str, field: str, row_number: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EndstepImportError(f"Строка {row_number}: {field} должно быть числом") from exc
    if minimum is not None and parsed < minimum:
        raise EndstepImportError(f"Строка {row_number}: {field} должно быть не меньше {minimum}")
    return parsed


def _optional_int(value: str, field: str, row_number: int) -> int | None:
    if not value:
        return None
    return _required_int(value, field, row_number)


def _optional_float(value: str, field: str, row_number: int) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EndstepImportError(f"Строка {row_number}: {field} должно быть числом") from exc


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()


class EndstepTournamentImporter:
    """Replace one local snapshot atomically when the same external event is reimported."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def import_csvs(
        self,
        *,
        external_key: str,
        slug: str,
        title: str,
        standings_path: str | Path,
        pairings_path: str | Path,
        decklists_path: str | Path,
        format_name: str = "Pauper",
    ) -> EndstepImportSummary:
        external_key = external_key.strip()
        slug = slug.strip().strip("/")
        title = title.strip()
        if not external_key or not slug or not title:
            raise EndstepImportError("external_key, slug и title не могут быть пустыми")

        standings_rows = _read_csv(
            standings_path,
            {"Place", "Player", "Status", "Match points", "Wins", "Losses", "Draws", "OMW%", "GW%", "OGW%"},
        )
        pairing_rows = _read_csv(
            pairings_path,
            {"Round", "Stage", "Table", "Player 1", "Player 2", "Games (P1-P2-draws)", "Result", "Winner"},
        )
        deck_rows = _read_csv(decklists_path, {"Place", "Player", "Section", "Quantity", "Card"})

        tournament = self.db.execute(
            select(models.EndstepTournament).where(models.EndstepTournament.external_key == external_key)
        ).scalar_one_or_none()
        slug_owner = self.db.execute(
            select(models.EndstepTournament).where(models.EndstepTournament.slug == slug)
        ).scalar_one_or_none()
        if slug_owner is not None and (tournament is None or slug_owner.id != tournament.id):
            raise EndstepImportError(f'URL slug "{slug}" уже занят другим турниром')

        if tournament is None:
            tournament = models.EndstepTournament(
                external_key=external_key,
                slug=slug,
                title=title,
                format_name=format_name.strip() or "Pauper",
            )
            self.db.add(tournament)
            self.db.flush()
        else:
            tournament.slug = slug
            tournament.title = title
            tournament.format_name = format_name.strip() or "Pauper"
            tournament.imported_at = models.utc_now()

            for model in (models.EndstepStanding, models.EndstepPairing, models.EndstepDeckCard):
                self.db.execute(delete(model).where(model.tournament_id == tournament.id))
            self.db.flush()

        users = self._users_by_endstep_name()
        matched_users: set[int] = set()

        for row_number, row in enumerate(standings_rows, start=2):
            player_name = row["Player"]
            if not player_name:
                raise EndstepImportError(f"Строка {row_number}: пустое имя игрока")
            user = users.get(_normalized_name(player_name))
            if user is not None:
                matched_users.add(user.id)
            self.db.add(
                models.EndstepStanding(
                    tournament_id=tournament.id,
                    place=_required_int(row["Place"], "Place", row_number, minimum=1),
                    player_name=player_name,
                    status=row["Status"] or None,
                    match_points=_required_int(row["Match points"], "Match points", row_number),
                    wins=_required_int(row["Wins"], "Wins", row_number),
                    losses=_required_int(row["Losses"], "Losses", row_number),
                    draws=_required_int(row["Draws"], "Draws", row_number),
                    omw_percent=_optional_float(row["OMW%"], "OMW%", row_number),
                    gw_percent=_optional_float(row["GW%"], "GW%", row_number),
                    ogw_percent=_optional_float(row["OGW%"], "OGW%", row_number),
                    user_id=user.id if user is not None else None,
                )
            )

        for row_number, row in enumerate(pairing_rows, start=2):
            self.db.add(
                models.EndstepPairing(
                    tournament_id=tournament.id,
                    round_number=_required_int(row["Round"], "Round", row_number, minimum=1),
                    stage=row["Stage"] or "Swiss",
                    table_number=_optional_int(row["Table"], "Table", row_number),
                    player1=row["Player 1"] or None,
                    player2=row["Player 2"] or None,
                    games=row["Games (P1-P2-draws)"] or None,
                    result=row["Result"] or None,
                    winner=row["Winner"] or None,
                )
            )

        for row_number, row in enumerate(deck_rows, start=2):
            player_name = row["Player"]
            card_name = row["Card"]
            if not player_name or not card_name:
                raise EndstepImportError(f"Строка {row_number}: Player и Card обязательны")
            section = row["Section"] or "Main"
            if section.casefold() not in {"main", "sideboard"}:
                raise EndstepImportError(f"Строка {row_number}: неизвестная секция {section}")
            self.db.add(
                models.EndstepDeckCard(
                    tournament_id=tournament.id,
                    place=_optional_int(row["Place"], "Place", row_number),
                    player_name=player_name,
                    section="Sideboard" if section.casefold() == "sideboard" else "Main",
                    quantity=_required_int(row["Quantity"], "Quantity", row_number, minimum=1),
                    card_name=card_name,
                    normalized_name=_normalized_name(card_name),
                )
            )

        self.db.commit()
        return EndstepImportSummary(
            tournament_id=tournament.id,
            standings=len(standings_rows),
            pairings=len(pairing_rows),
            deck_cards=len(deck_rows),
            matched_users=len(matched_users),
        )

    def _users_by_endstep_name(self) -> dict[str, models.User]:
        users = self.db.execute(select(models.User).where(models.User.endstep_username.is_not(None))).scalars()
        result: dict[str, models.User] = {}
        for user in users:
            if user.endstep_username:
                result[_normalized_name(user.endstep_username)] = user
        return result
