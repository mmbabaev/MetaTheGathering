from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from core import models
from services.archetype import ArchetypeService
from services.season_stats import PopularDeck
from services.top_archetypes import TopArchetypeSnapshotService

AS_OF = datetime(2026, 8, 19)


def _snapshot(*decks: PopularDeck, complete_tournaments: int = 12):
    return SimpleNamespace(
        popular_decks=list(decks),
        quality=SimpleNamespace(complete_tournaments=complete_tournaments),
    )


def _popular(rank: int, deck: str, participations: int = 10, players: int = 5) -> PopularDeck:
    return PopularDeck(
        rank=rank,
        deck=deck,
        participations=participations,
        players=players,
        registered_participations=participations,
    )


def _used_in_closed_tournament(db, archetype: models.Archetype, *, count: int) -> None:
    tournament = models.Tournament(
        title=f"Usage {archetype.name}",
        chat_id=-100 - archetype.id,
        status=models.TournamentStatus.CLOSED,
    )
    db.add(tournament)
    db.flush()
    for index in range(count):
        user = models.User(tg_id=-(archetype.id * 100 + index + 1), first_name=f"P{index}")
        db.add(user)
        db.flush()
        db.add(models.Participant(tournament_id=tournament.id, user_id=user.id, archetype_id=archetype.id))
    db.commit()


def test_refresh_persists_snapshot_and_clears_stale_ranks(db):
    stale = models.Archetype(name="Stale", meta_rank=1)
    blue = models.Archetype(name="Blue Terror")
    affinity = models.Archetype(name="Grixis Affinity")
    db.add_all([stale, blue, affinity])
    db.commit()

    snapshot = _snapshot(_popular(1, "Blue Terror"), _popular(2, "Grixis Affinity"))
    with patch("services.top_archetypes.SeasonStatsService.build_snapshot", return_value=snapshot) as build:
        result = TopArchetypeSnapshotService(db).refresh(as_of=AS_OF)

    assert result.updated is True
    assert [row.archetype_name for row in result.assignments] == ["Blue Terror", "Grixis Affinity"]
    assert stale.meta_rank is None
    assert blue.meta_rank == 1
    assert affinity.meta_rank == 2
    assert [row.name for row in ArchetypeService(db).list_top_archetypes()] == [
        "Blue Terror",
        "Grixis Affinity",
    ]
    assert build.call_args.kwargs["deck_window_days"] == 365
    assert build.call_args.kwargs["top_decks"] == 10


def test_refresh_prefers_exact_public_name_over_variants_and_custom_rows(db):
    exact = models.Archetype(name="BG Gardens", general_name="BG Gardens")
    popular_variant = models.Archetype(name="Gardens", general_name="BG Gardens")
    custom_exact = models.Archetype(name="Spy Walls", general_name="Spy Walls", is_custom=True)
    public_spy = models.Archetype(name="Spy Combo", general_name="Spy Walls")
    db.add_all([exact, popular_variant, custom_exact, public_spy])
    db.commit()
    _used_in_closed_tournament(db, popular_variant, count=3)

    snapshot = _snapshot(_popular(1, "BG Gardens"), _popular(2, "Spy Walls"))
    with patch("services.top_archetypes.SeasonStatsService.build_snapshot", return_value=snapshot):
        result = TopArchetypeSnapshotService(db).refresh(as_of=AS_OF)

    assert [(row.general_name, row.archetype_name) for row in result.assignments] == [
        ("BG Gardens", "BG Gardens"),
        ("Spy Walls", "Spy Combo"),
    ]
    assert custom_exact.meta_rank is None


def test_refresh_uses_most_played_public_variant_when_exact_name_is_absent(db):
    rare = models.Archetype(name="Combo Walls", general_name="Spy Walls")
    popular = models.Archetype(name="Spy Combo", general_name="Spy Walls")
    db.add_all([rare, popular])
    db.commit()
    _used_in_closed_tournament(db, rare, count=1)
    _used_in_closed_tournament(db, popular, count=3)

    with patch(
        "services.top_archetypes.SeasonStatsService.build_snapshot",
        return_value=_snapshot(_popular(1, "Spy Walls")),
    ):
        result = TopArchetypeSnapshotService(db).refresh(as_of=AS_OF)

    assert result.assignments[0].archetype_name == "Spy Combo"


def test_empty_refresh_keeps_last_known_good_snapshot(db):
    previous = models.Archetype(name="Blue Terror", meta_rank=1)
    db.add(previous)
    db.commit()

    with patch(
        "services.top_archetypes.SeasonStatsService.build_snapshot",
        return_value=_snapshot(complete_tournaments=0),
    ):
        result = TopArchetypeSnapshotService(db).refresh(as_of=AS_OF)

    assert result.updated is False
    assert previous.meta_rank == 1
