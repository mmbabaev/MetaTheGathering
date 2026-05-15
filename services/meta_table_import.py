"""Import tournament meta from the plain-text table format produced by /recognize-meta."""

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services import errors
from services.archetype import ArchetypeService
from services.tournament import TournamentService
from services.user import UserService


@dataclass
class MetaTableImportResult:
    registered: int = 0
    deck_updated: int = 0
    deck_skipped: int = 0  # player already had a deck
    pairings_saved: int = 0
    unknown_decks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.registered:
            lines.append(f"✅ Добавлено новых игроков: {self.registered}")
        if self.deck_updated:
            lines.append(f"🃏 Обновлено колод: {self.deck_updated}")
        if self.deck_skipped:
            lines.append(f"⏭ Пропущено (колода уже была): {self.deck_skipped}")
        if self.pairings_saved:
            lines.append(f"🤝 Записано паров: {self.pairings_saved}")
        if self.unknown_decks:
            names = ", ".join(self.unknown_decks[:5])
            if len(self.unknown_decks) > 5:
                names += f" +{len(self.unknown_decks) - 5}"
            lines.append(f"❓ Колода не распознана: {names}")
        if self.errors:
            for e in self.errors[:3]:
                lines.append(f"⚠️ {e}")
        return "\n".join(lines) if lines else "Ничего не импортировано."


def parse_meta_table(text: str) -> tuple[list[tuple[str, Optional[str]]], dict[int, list[tuple[str, str]]]]:
    """Parse the /recognize-meta table format.

    Returns:
        players: list of (full_name, deck_name_or_None)
        pairings: dict of round_number → list of (player1_name, player2_name)
    """
    players: list[tuple[str, Optional[str]]] = []
    pairings: dict[int, list[tuple[str, str]]] = {}

    current_round: Optional[int] = None
    in_players = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Section headers (start with ##)
        if re.match(r"^##\s*Игроки", line, re.IGNORECASE):
            in_players = True
            current_round = None
            continue

        m = re.match(r"^##\s*Раунд\s*(\d+)", line, re.IGNORECASE)
        if m:
            current_round = int(m.group(1))
            in_players = False
            pairings.setdefault(current_round, [])
            continue

        # Single-# lines are comments (e.g. "# Не распознано: 1")
        if line.startswith("#"):
            continue

        if in_players:
            if "|" in line:
                parts = line.split("|", 1)
                name = parts[0].strip()
                deck_raw = parts[1].strip()
                deck = deck_raw if deck_raw and deck_raw != "?" else None
                if name:
                    players.append((name, deck))
            continue

        if current_round is not None:
            # Pairing line: "Name1 SCORE Name2" or "Name1 BYE"
            bye_m = re.match(r"^(.+?)\s+BYE\s*$", line, re.IGNORECASE)
            if bye_m:
                pairings[current_round].append((bye_m.group(1).strip(), "BYE"))
                continue

            # Match score pattern: digits-digits or ?-? or digit-D etc.
            score_m = re.search(r"\s+[\dD?]+-[\dD?]+\s+", line)
            if score_m:
                left = line[: score_m.start()].strip()
                right = line[score_m.end() :].strip()
                if left and right:
                    pairings[current_round].append((left, right))

    return players, pairings


class MetaTableImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._user_svc = UserService(db)
        self._arch_svc = ArchetypeService(db)
        self._svc = TournamentService(db)

    def import_from_table(self, tournament_id: int, text: str, added_by_tg_id: int) -> MetaTableImportResult:
        tournament = self.db.get(models.Tournament, tournament_id)
        if tournament is None:
            raise errors.TournamentNotFound(f"Tournament {tournament_id} not found")

        result = MetaTableImportResult()
        players, pairings = parse_meta_table(text)

        for full_name, deck_name in players:
            self._import_player(tournament_id, full_name, deck_name, added_by_tg_id, result)

        for round_number, pairs in pairings.items():
            for p1_name, p2_name in pairs:
                self._save_pairing(tournament_id, round_number, p1_name, p2_name, result)

        return result

    def _import_player(
        self,
        tournament_id: int,
        full_name: str,
        deck_name: Optional[str],
        added_by_tg_id: int,
        result: MetaTableImportResult,
    ) -> None:
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else None

        user, was_created = self._user_svc.get_or_create_by_name(first_name, last_name)

        participant = self.db.execute(
            select(models.Participant).where(
                models.Participant.tournament_id == tournament_id,
                models.Participant.user_id == user.id,
            )
        ).scalar_one_or_none()

        archetype = None
        if deck_name:
            archetype = self._arch_svc.get_or_create_by_name(deck_name, is_custom=True)
        else:
            result.unknown_decks.append(full_name)

        if participant is None:
            # Register new participant
            new_p = models.Participant(
                tournament_id=tournament_id,
                user_id=user.id,
                archetype_id=archetype.id if archetype else None,
                added_by_admin=True,
                deck_added_by_tg_id=added_by_tg_id if archetype else None,
                created_at=models.utc_now(),
                updated_at=models.utc_now(),
            )
            self.db.add(new_p)
            result.registered += 1
        else:
            # Smart update: skip if player already has a deck
            if participant.archetype_id is not None:
                result.deck_skipped += 1
            elif archetype:
                participant.archetype_id = archetype.id
                participant.deck_added_by_tg_id = added_by_tg_id
                participant.updated_at = models.utc_now()
                result.deck_updated += 1

        self.db.commit()

    def _save_pairing(
        self,
        tournament_id: int,
        round_number: int,
        p1_name: str,
        p2_name: str,
        result: MetaTableImportResult,
    ) -> None:
        for player, opponent in [(p1_name, p2_name), (p2_name, p1_name)]:
            if opponent.upper() == "BYE":
                opponent = None
            existing = self.db.execute(
                select(models.RoundPairing).where(
                    models.RoundPairing.tournament_id == tournament_id,
                    models.RoundPairing.round_number == round_number,
                    models.RoundPairing.player_name == player,
                )
            ).scalar_one_or_none()
            if existing is None:
                self.db.add(
                    models.RoundPairing(
                        tournament_id=tournament_id,
                        round_number=round_number,
                        player_name=player,
                        opponent_name=opponent,
                    )
                )
                result.pairings_saved += 1
        self.db.commit()
