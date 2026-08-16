"""Read-only historical statistics for seasonal achievement design.

The snapshot deliberately uses only primary tournament data.  It does not write
achievement progress, create boards, or send Telegram messages.  A tournament is
eligible when it is closed, has pairings, and every non-bye pairing has a score.
Participants who registered but never appeared in pairings are not counted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from pydantic import BaseModel, computed_field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from services.achievements.history import display_name, tournament_date


class MatchRecord(BaseModel):
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @computed_field
    @property
    def matches(self) -> int:
        return self.wins + self.losses + self.draws

    @computed_field
    @property
    def winrate(self) -> float | None:
        return round(self.wins * 100 / self.matches, 2) if self.matches else None


class HeadToHeadCandidate(BaseModel):
    opponent_user_id: int
    opponent_name: str
    opponent_registered: bool
    matches: int
    wins: int
    losses: int
    draws: int
    winrate: float
    last_played_at: datetime


class WinrateChange(BaseModel):
    previous: MatchRecord
    current: MatchRecord
    delta_percentage_points: float | None
    eligible: bool


class PlayerSeasonStats(BaseModel):
    user_id: int
    name: str
    registered: bool
    record: MatchRecord
    worst_opponent: HeadToHeadCandidate | None
    winrate_change: WinrateChange


class PopularDeck(BaseModel):
    rank: int
    deck: str
    participations: int
    players: int
    registered_participations: int


class SeasonStatsQuality(BaseModel):
    tournaments_scanned: int
    complete_tournaments: int
    excluded_not_closed: int
    excluded_incomplete: int
    pairing_rows: int
    scored_matches: int
    matched_player_rows: int
    unmatched_player_rows: int
    actual_participations: int
    registered_participations: int
    participants_without_pairing: int


class SeasonStatsSnapshot(BaseModel):
    as_of: datetime
    club: str | None
    history_days: int
    deck_window_days: int
    winrate_window_days: int
    min_h2h_matches: int
    min_window_matches: int
    quality: SeasonStatsQuality
    popular_decks: list[PopularDeck]
    players: list[PlayerSeasonStats]


class _MutableRecord:
    def __init__(self) -> None:
        self.wins = 0
        self.losses = 0
        self.draws = 0

    def add(self, player_wins: int, opponent_wins: int) -> None:
        if player_wins > opponent_wins:
            self.wins += 1
        elif player_wins < opponent_wins:
            self.losses += 1
        else:
            self.draws += 1

    def freeze(self) -> MatchRecord:
        return MatchRecord(wins=self.wins, losses=self.losses, draws=self.draws)


def _normalized_name(value: str | None) -> str:
    value = re.sub(r"\(\s*\d+\s*points?\s*\)", "", value or "", flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip().casefold().replace("ё", "е")


def _user_name_variants(user: models.User) -> set[str]:
    first = _normalized_name(user.first_name)
    last = _normalized_name(user.last_name)
    variants = {
        _normalized_name(user.display_name),
        _normalized_name(user.username),
    }
    if first and last:
        variants.update({f"{first} {last}", f"{last} {first}"})
    elif first:
        variants.add(first)
        words = first.split()
        if len(words) == 2:
            variants.add(f"{words[1]} {words[0]}")
    return {variant for variant in variants if variant}


def _complete_pairings(rows: list[models.RoundPairing]) -> bool:
    return bool(rows) and all(
        row.opponent_name is None or (row.player_wins is not None and row.opponent_wins is not None)
        for row in rows
    )


class SeasonStatsService:
    """Build a frozen, read-only data snapshot as it looked at season start."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build_snapshot(
        self,
        *,
        as_of: datetime,
        club: str | None = None,
        history_days: int = 365,
        deck_window_days: int = 120,
        winrate_window_days: int = 90,
        top_decks: int = 10,
        min_h2h_matches: int = 3,
        min_window_matches: int = 5,
    ) -> SeasonStatsSnapshot:
        for name, value in {
            "history_days": history_days,
            "deck_window_days": deck_window_days,
            "winrate_window_days": winrate_window_days,
            "top_decks": top_decks,
            "min_h2h_matches": min_h2h_matches,
            "min_window_matches": min_window_matches,
        }.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        horizon_days = max(history_days, deck_window_days, winrate_window_days * 2)
        since = as_of - timedelta(days=horizon_days)
        tournaments = list(self.db.execute(select(models.Tournament)).scalars().all())
        tournaments = [
            tournament
            for tournament in tournaments
            if since <= tournament_date(tournament) < as_of
            and (club is None or (tournament.club or "").casefold() == club.casefold())
        ]
        tournaments.sort(key=lambda tournament: (tournament_date(tournament), tournament.id))

        tournament_ids = [tournament.id for tournament in tournaments]
        pairings = self._pairings_by_tournament(tournament_ids)
        participants = self._participants_by_tournament(tournament_ids)

        excluded_not_closed = 0
        excluded_incomplete = 0
        eligible: list[models.Tournament] = []
        for tournament in tournaments:
            if tournament.status != models.TournamentStatus.CLOSED:
                excluded_not_closed += 1
                continue
            if not _complete_pairings(pairings[tournament.id]):
                excluded_incomplete += 1
                continue
            eligible.append(tournament)

        overall: dict[int, _MutableRecord] = defaultdict(_MutableRecord)
        previous: dict[int, _MutableRecord] = defaultdict(_MutableRecord)
        current: dict[int, _MutableRecord] = defaultdict(_MutableRecord)
        h2h: dict[tuple[int, int], _MutableRecord] = defaultdict(_MutableRecord)
        h2h_last_played: dict[tuple[int, int], datetime] = {}
        users: dict[int, models.User] = {}
        deck_users: dict[str, set[int]] = defaultdict(set)
        deck_participations: dict[str, int] = defaultdict(int)
        deck_registered_participations: dict[str, int] = defaultdict(int)

        pairing_rows = matched_rows = unmatched_rows = 0
        participants_without_pairing = 0
        actual_participations = 0
        registered_participations = 0
        unique_match_keys: set[tuple[object, ...]] = set()
        seen_player_rounds: set[tuple[int, int, int]] = set()

        current_since = as_of - timedelta(days=winrate_window_days)
        previous_since = current_since - timedelta(days=winrate_window_days)
        history_since = as_of - timedelta(days=history_days)
        deck_since = as_of - timedelta(days=deck_window_days)

        for tournament in eligible:
            played_at = tournament_date(tournament)
            name_to_user = self._name_map(participants[tournament.id])
            played_user_ids: set[int] = set()

            for pairing in pairings[tournament.id]:
                pairing_rows += 1
                player = name_to_user.get(_normalized_name(pairing.player_name))
                if player is None:
                    unmatched_rows += 1
                    continue
                matched_rows += 1
                users[player.id] = player
                played_user_ids.add(player.id)

                if pairing.opponent_name is None:
                    continue
                if pairing.player_wins is None or pairing.opponent_wins is None:
                    continue
                player_round_key = (tournament.id, pairing.round_number, player.id)
                if player_round_key in seen_player_rounds:
                    continue
                seen_player_rounds.add(player_round_key)

                if played_at >= history_since:
                    overall[player.id].add(pairing.player_wins, pairing.opponent_wins)
                if previous_since <= played_at < current_since:
                    previous[player.id].add(pairing.player_wins, pairing.opponent_wins)
                elif current_since <= played_at < as_of:
                    current[player.id].add(pairing.player_wins, pairing.opponent_wins)

                opponent = name_to_user.get(_normalized_name(pairing.opponent_name))
                if opponent is None or opponent.id == player.id:
                    match_names = sorted((_normalized_name(pairing.player_name), _normalized_name(pairing.opponent_name)))
                    unique_match_keys.add((tournament.id, pairing.round_number, *match_names))
                    continue
                users[opponent.id] = opponent
                unique_match_keys.add((tournament.id, pairing.round_number, *sorted((player.id, opponent.id))))
                if played_at >= history_since:
                    h2h[player.id, opponent.id].add(pairing.player_wins, pairing.opponent_wins)
                    h2h_last_played[player.id, opponent.id] = max(
                        played_at,
                        h2h_last_played.get((player.id, opponent.id), played_at),
                    )

            participant_by_user = {participant.user_id: participant for participant in participants[tournament.id]}
            participants_without_pairing += len(set(participant_by_user) - played_user_ids)
            for user_id in played_user_ids:
                participant = participant_by_user.get(user_id)
                if participant is None:
                    continue
                actual_participations += 1
                is_registered = participant.user.tg_id > 0
                if is_registered:
                    registered_participations += 1
                if played_at < deck_since or participant.archetype is None:
                    continue
                deck = participant.archetype.general_name or participant.archetype.name
                deck_participations[deck] += 1
                deck_users[deck].add(user_id)
                if is_registered:
                    deck_registered_participations[deck] += 1

        popular_decks = self._popular_decks(
            deck_participations,
            deck_users,
            deck_registered_participations,
            limit=top_decks,
        )
        player_rows = [
            self._player_stats(
                user,
                overall[user_id].freeze(),
                previous[user_id].freeze(),
                current[user_id].freeze(),
                h2h,
                h2h_last_played,
                users,
                min_h2h_matches=min_h2h_matches,
                min_window_matches=min_window_matches,
            )
            for user_id, user in users.items()
            if overall[user_id].freeze().matches
        ]
        player_rows.sort(key=lambda row: (-row.record.matches, row.name.casefold(), row.user_id))

        return SeasonStatsSnapshot(
            as_of=as_of,
            club=club,
            history_days=history_days,
            deck_window_days=deck_window_days,
            winrate_window_days=winrate_window_days,
            min_h2h_matches=min_h2h_matches,
            min_window_matches=min_window_matches,
            quality=SeasonStatsQuality(
                tournaments_scanned=len(tournaments),
                complete_tournaments=len(eligible),
                excluded_not_closed=excluded_not_closed,
                excluded_incomplete=excluded_incomplete,
                pairing_rows=pairing_rows,
                scored_matches=len(unique_match_keys),
                matched_player_rows=matched_rows,
                unmatched_player_rows=unmatched_rows,
                actual_participations=actual_participations,
                registered_participations=registered_participations,
                participants_without_pairing=participants_without_pairing,
            ),
            popular_decks=popular_decks,
            players=player_rows,
        )

    def _pairings_by_tournament(self, tournament_ids: list[int]) -> dict[int, list[models.RoundPairing]]:
        result: dict[int, list[models.RoundPairing]] = defaultdict(list)
        if not tournament_ids:
            return result
        rows = self.db.execute(
            select(models.RoundPairing).where(models.RoundPairing.tournament_id.in_(tournament_ids))
        ).scalars()
        for row in rows:
            result[row.tournament_id].append(row)
        return result

    def _participants_by_tournament(self, tournament_ids: list[int]) -> dict[int, list[models.Participant]]:
        result: dict[int, list[models.Participant]] = defaultdict(list)
        if not tournament_ids:
            return result
        rows = self.db.execute(
            select(models.Participant).where(models.Participant.tournament_id.in_(tournament_ids))
        ).scalars()
        for row in rows:
            result[row.tournament_id].append(row)
        return result

    @staticmethod
    def _name_map(participants: Iterable[models.Participant]) -> dict[str, models.User]:
        candidates: dict[str, list[models.User]] = defaultdict(list)
        for participant in participants:
            for variant in _user_name_variants(participant.user):
                candidates[variant].append(participant.user)
        return {
            variant: matches[0]
            for variant, matches in candidates.items()
            if len({match.id for match in matches}) == 1
        }

    @staticmethod
    def _popular_decks(
        participations: dict[str, int],
        users: dict[str, set[int]],
        registered: dict[str, int],
        *,
        limit: int,
    ) -> list[PopularDeck]:
        ordered = sorted(participations, key=lambda deck: (-participations[deck], deck.casefold()))[:limit]
        return [
            PopularDeck(
                rank=index,
                deck=deck,
                participations=participations[deck],
                players=len(users[deck]),
                registered_participations=registered[deck],
            )
            for index, deck in enumerate(ordered, start=1)
        ]

    @staticmethod
    def _player_stats(
        user: models.User,
        record: MatchRecord,
        previous: MatchRecord,
        current: MatchRecord,
        h2h: dict[tuple[int, int], _MutableRecord],
        last_played: dict[tuple[int, int], datetime],
        users: dict[int, models.User],
        *,
        min_h2h_matches: int,
        min_window_matches: int,
    ) -> PlayerSeasonStats:
        candidates: list[HeadToHeadCandidate] = []
        for (player_id, opponent_id), mutable in h2h.items():
            if player_id != user.id:
                continue
            result = mutable.freeze()
            if result.matches < min_h2h_matches or result.winrate is None:
                continue
            opponent = users[opponent_id]
            candidates.append(
                HeadToHeadCandidate(
                    opponent_user_id=opponent_id,
                    opponent_name=display_name(opponent),
                    opponent_registered=opponent.tg_id > 0,
                    matches=result.matches,
                    wins=result.wins,
                    losses=result.losses,
                    draws=result.draws,
                    winrate=result.winrate,
                    last_played_at=last_played[player_id, opponent_id],
                )
            )
        candidates.sort(key=lambda row: (row.winrate, -row.matches, row.opponent_name.casefold()))

        eligible = previous.matches >= min_window_matches and current.matches >= min_window_matches
        delta = None
        if previous.winrate is not None and current.winrate is not None:
            delta = round(current.winrate - previous.winrate, 2)
        return PlayerSeasonStats(
            user_id=user.id,
            name=display_name(user),
            registered=user.tg_id > 0,
            record=record,
            worst_opponent=candidates[0] if candidates else None,
            winrate_change=WinrateChange(
                previous=previous,
                current=current,
                delta_percentage_points=delta,
                eligible=eligible,
            ),
        )
