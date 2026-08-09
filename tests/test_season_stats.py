from __future__ import annotations

from datetime import datetime

from core import models
from services.season_stats import SeasonStatsService

AS_OF = datetime(2026, 9, 1)


def _user(db, tg_id: int, first: str, last: str) -> models.User:
    row = models.User(tg_id=tg_id, first_name=first, last_name=last)
    db.add(row)
    db.flush()
    return row


def _deck(db, name: str, *, general_name: str | None = None) -> models.Archetype:
    row = models.Archetype(name=name, general_name=general_name)
    db.add(row)
    db.flush()
    return row


def _tournament(
    db,
    *,
    played_at: datetime,
    participants: list[tuple[models.User, models.Archetype | None]],
    matches: list[tuple[str, str, int | None, int | None]],
    status: models.TournamentStatus = models.TournamentStatus.CLOSED,
    club: str = "Goldfish",
) -> models.Tournament:
    tournament = models.Tournament(
        title=f"Daily {played_at:%Y-%m-%d}",
        chat_id=-100,
        club=club,
        status=status,
        started_at=played_at,
        created_at=played_at,
    )
    db.add(tournament)
    db.flush()
    for user, archetype in participants:
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype.id if archetype else None))
    for round_number, (player, opponent, player_wins, opponent_wins) in enumerate(matches, start=1):
        db.add_all(
            [
                models.RoundPairing(
                    tournament_id=tournament.id,
                    round_number=round_number,
                    player_name=player,
                    opponent_name=opponent,
                    player_wins=player_wins,
                    opponent_wins=opponent_wins,
                ),
                models.RoundPairing(
                    tournament_id=tournament.id,
                    round_number=round_number,
                    player_name=opponent,
                    opponent_name=player,
                    player_wins=opponent_wins,
                    opponent_wins=player_wins,
                ),
            ]
        )
    db.commit()
    return tournament


def test_snapshot_uses_only_closed_complete_tournaments_and_excludes_no_shows(db):
    alice = _user(db, 101, "Alice", "Smith")
    bob = _user(db, 102, "Bob", "Jones")
    carol = _user(db, 103, "Carol", "White")
    red = _deck(db, "Kuldotha Burn", general_name="Kuldotha Red")
    red_variant = _deck(db, "Mono Red", general_name="Kuldotha Red")
    affinity = _deck(db, "Grixis Affinity")

    _tournament(
        db,
        played_at=datetime(2026, 8, 1),
        participants=[(alice, red), (bob, red_variant), (carol, affinity)],
        matches=[("Smith Alice", "Bob Jones", 2, 0)],
    )
    _tournament(
        db,
        played_at=datetime(2026, 8, 10),
        participants=[(alice, affinity), (bob, affinity)],
        matches=[("Alice Smith", "Bob Jones", 2, 1)],
        status=models.TournamentStatus.ONGOING,
    )
    _tournament(
        db,
        played_at=datetime(2026, 8, 20),
        participants=[(alice, affinity), (bob, affinity)],
        matches=[("Alice Smith", "Bob Jones", None, None)],
    )

    snapshot = SeasonStatsService(db).build_snapshot(as_of=AS_OF, min_h2h_matches=1, min_window_matches=1)

    assert snapshot.quality.tournaments_scanned == 3
    assert snapshot.quality.complete_tournaments == 1
    assert snapshot.quality.excluded_not_closed == 1
    assert snapshot.quality.excluded_incomplete == 1
    assert snapshot.quality.scored_matches == 1
    assert snapshot.quality.actual_participations == 2
    assert snapshot.quality.participants_without_pairing == 1
    assert [(row.deck, row.participations, row.players) for row in snapshot.popular_decks] == [
        ("Kuldotha Red", 2, 2)
    ]
    assert {row.name for row in snapshot.players} == {"Smith Alice", "Jones Bob"}


def test_snapshot_builds_worst_h2h_and_equal_winrate_windows(db):
    alice = _user(db, 201, "Alice", "Smith")
    bob = _user(db, -1, "Bob", "Jones")
    deck = _deck(db, "Burn")

    for played_at, score in [
        (datetime(2026, 7, 10), (0, 2)),
        (datetime(2026, 7, 20), (1, 2)),
        (datetime(2026, 8, 10), (2, 0)),
        (datetime(2026, 8, 20), (0, 2)),
    ]:
        _tournament(
            db,
            played_at=played_at,
            participants=[(alice, deck), (bob, deck)],
            matches=[("Smith Alice", "Jones Bob", *score)],
        )

    snapshot = SeasonStatsService(db).build_snapshot(
        as_of=AS_OF,
        winrate_window_days=30,
        min_window_matches=2,
        min_h2h_matches=3,
    )
    alice_stats = next(row for row in snapshot.players if row.user_id == alice.id)

    assert alice_stats.record.matches == 4
    assert alice_stats.record.winrate == 25.0
    assert alice_stats.worst_opponent is not None
    assert alice_stats.worst_opponent.opponent_user_id == bob.id
    assert alice_stats.worst_opponent.matches == 4
    assert alice_stats.worst_opponent.winrate == 25.0
    assert alice_stats.worst_opponent.opponent_registered is False
    assert alice_stats.winrate_change.previous.winrate == 0.0
    assert alice_stats.winrate_change.current.winrate == 50.0
    assert alice_stats.winrate_change.delta_percentage_points == 50.0
    assert alice_stats.winrate_change.eligible is True
    assert '"matches":4' in snapshot.model_dump_json()


def test_snapshot_filters_club_case_insensitively(db):
    alice = _user(db, 301, "Alice", "Smith")
    bob = _user(db, 302, "Bob", "Jones")
    deck = _deck(db, "Burn")
    _tournament(
        db,
        played_at=datetime(2026, 8, 1),
        participants=[(alice, deck), (bob, deck)],
        matches=[("Alice Smith", "Bob Jones", 2, 0)],
        club="Goldfish",
    )
    _tournament(
        db,
        played_at=datetime(2026, 8, 2),
        participants=[(alice, deck), (bob, deck)],
        matches=[("Alice Smith", "Bob Jones", 0, 2)],
        club="Edinorog",
    )

    snapshot = SeasonStatsService(db).build_snapshot(as_of=AS_OF, club="goldfish")

    assert snapshot.quality.tournaments_scanned == 1
    assert snapshot.quality.complete_tournaments == 1
    assert snapshot.quality.scored_matches == 1
