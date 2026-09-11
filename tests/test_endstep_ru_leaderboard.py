from unittest.mock import MagicMock

from core import models
from services.endstep import EndstepLeaderboardPlayer, EndstepPlayerLookup
from services.endstep_ru_leaderboard import EndstepRuLeaderboardService
from services.user import UserService


def _player(username: str, *, rank: int | None, rating: int, provisional: bool = False):
    return EndstepLeaderboardPlayer(
        userId=f"endstep-{username}",
        username=username,
        rank=rank,
        rating=rating,
        rd=75,
        wins=12,
        losses=5,
        draws=1,
        matchesPlayed=18,
        provisional=provisional,
    )


def _tournament(db, *, club: str):
    tournament = models.Tournament(title=f"{club} tournament", chat_id=100, club=club)
    db.add(tournament)
    db.commit()
    return tournament


def _participate(db, tournament, user):
    db.add(models.Participant(tournament_id=tournament.id, user_id=user.id))
    db.commit()


def test_matches_only_real_users_from_endstep_ru_tournaments_and_sorts_like_site(db):
    users = UserService(db)
    first = users.get_or_create(tg_id=9101, first_name="First")
    first.endstep_username = "FirstNick"
    second = users.get_or_create(tg_id=9102, first_name="Second")
    second.endstep_username = "SecondNick"
    provisional = users.get_or_create(tg_id=9103, first_name="New")
    provisional.endstep_username = "NewNick"
    missing = users.get_or_create(tg_id=9104, first_name="Missing")
    missing.endstep_username = "MissingNick"
    no_nick = users.get_or_create(tg_id=9105, first_name="No nick")
    other_club = users.get_or_create(tg_id=9106, first_name="Other")
    other_club.endstep_username = "OtherNick"
    placeholder = users.get_or_create(tg_id=-9107, first_name="Placeholder")
    placeholder.endstep_username = "PlaceholderNick"
    db.commit()

    endstep = _tournament(db, club="Endstep-ru")
    endstep_case_variant = _tournament(db, club="ENDSTEP-RU")
    goldfish = _tournament(db, club="Goldfish")
    for user in (first, second, provisional, missing, no_nick, placeholder):
        _participate(db, endstep, user)
    _participate(db, endstep_case_variant, first)
    _participate(db, goldfish, other_club)

    client = MagicMock()
    client.find_players.return_value = (
        EndstepPlayerLookup(requested_username="FirstNick", player=_player("FirstNick", rank=25, rating=1600)),
        EndstepPlayerLookup(requested_username="SecondNick", player=_player("SecondNick", rank=4, rating=1700)),
        EndstepPlayerLookup(
            requested_username="NewNick",
            player=_player("NewNick", rank=None, rating=1800, provisional=True),
        ),
        EndstepPlayerLookup(requested_username="MissingNick", player=None),
    )

    snapshot = EndstepRuLeaderboardService(db, client).calculate()

    client.find_players.assert_called_once_with(["FirstNick", "SecondNick", "NewNick", "MissingNick"])
    assert snapshot.candidate_count == 4
    assert [(row.position, row.username, row.site_rank) for row in snapshot.rows] == [
        (1, "SecondNick", 4),
        (2, "FirstNick", 25),
        (3, "NewNick", None),
    ]
    assert snapshot.rows[-1].provisional is True
    assert snapshot.missing_usernames == ("MissingNick",)


def test_empty_bot_roster_does_not_call_endstep(db):
    client = MagicMock()

    snapshot = EndstepRuLeaderboardService(db, client).calculate()

    assert snapshot.candidate_count == 0
    assert snapshot.rows == ()
    assert snapshot.missing_usernames == ()
    assert snapshot.ambiguous_usernames == ()
    client.find_players.assert_not_called()


def test_duplicate_endstep_username_is_excluded_and_reported(db):
    user = UserService(db).get_or_create(tg_id=9110, first_name="Duplicate")
    user.endstep_username = "counterspell"
    db.commit()
    _participate(db, _tournament(db, club="Endstep-ru"), user)
    ranked = _player("counterspell", rank=613, rating=1156)
    provisional = _player("counterspell", rank=None, rating=1613, provisional=True)
    client = MagicMock()
    client.find_players.return_value = (
        EndstepPlayerLookup(
            requested_username="counterspell",
            player=None,
            exact_matches=(ranked, provisional),
        ),
    )

    snapshot = EndstepRuLeaderboardService(db, client).calculate()

    assert snapshot.rows == ()
    assert snapshot.missing_usernames == ()
    assert snapshot.ambiguous_usernames == ("counterspell",)
