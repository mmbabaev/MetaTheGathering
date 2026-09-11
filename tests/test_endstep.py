from unittest.mock import MagicMock, call

import pytest
import requests

from services.endstep import EndstepApiError, EndstepClient


def _response(body, *, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    return response


def _player(username: str, *, rank: int | None = 7, provisional: bool = False):
    return {
        "userId": f"user-{username}",
        "username": username,
        "rank": rank,
        "rating": 1632,
        "rd": 74,
        "wins": 12,
        "losses": 5,
        "draws": 1,
        "matchesPlayed": 18,
        "provisional": provisional,
        "recentForm": ["won", "lost"],
    }


def test_finds_exact_players_with_one_guest_session():
    session = MagicMock()
    session.post.return_value = _response({"user": {"id": "integration"}})
    session.get.side_effect = [
        _response([{"formatId": "pauper", "displayName": "Pauper"}]),
        _response(
            {
                "rows": [_player("Annabelle"), _player("ANNA")],
                "total": 2,
                "provisionalCount": 0,
            }
        ),
        _response({"rows": [], "total": 0, "provisionalCount": 0}),
    ]
    client = EndstepClient("https://endstep.example/", session=session, timeout=10)

    result = client.find_players(["  anna ", "Missing", "ANNA"])

    assert [row.requested_username for row in result] == ["anna", "Missing"]
    assert result[0].player is not None
    assert result[0].player.username == "ANNA"
    assert result[0].player.rank == 7
    assert result[1].player is None
    session.post.assert_called_once_with(
        "https://endstep.example/api/auth/guest",
        json={},
        timeout=10,
    )
    assert session.get.call_args_list == [
        call("https://endstep.example/api/ranked/queues", params=None, timeout=10),
        call(
            "https://endstep.example/api/ranked/leaderboard",
            params={"format": "pauper", "limit": 50, "offset": 0, "q": "anna"},
            timeout=10,
        ),
        call(
            "https://endstep.example/api/ranked/leaderboard",
            params={"format": "pauper", "limit": 50, "offset": 0, "q": "Missing"},
            timeout=10,
        ),
    ]


def test_supports_wrapped_queue_response_and_provisional_player():
    session = MagicMock()
    session.post.return_value = _response({"user": {"id": "integration"}})
    session.get.side_effect = [
        _response({"queues": [{"formatId": "pauper", "displayName": "Pauper"}]}),
        _response(
            {
                "rows": [_player("NewPlayer", rank=None, provisional=True)],
                "total": 0,
                "provisionalCount": 1,
            }
        ),
    ]

    result = EndstepClient(session=session).find_players(["newplayer"])

    assert result[0].player is not None
    assert result[0].player.rank is None
    assert result[0].player.provisional is True


def test_reauthenticates_once_after_expired_cookie():
    session = MagicMock()
    session.post.side_effect = [
        _response({"user": {"id": "integration"}}),
        _response({"user": {"id": "integration"}}),
    ]
    session.get.side_effect = [
        _response({"error": "Unauthorized"}, status=401),
        _response([{"formatId": "pauper", "displayName": "Pauper"}]),
    ]
    client = EndstepClient(session=session)

    assert client.resolve_format_id() == "pauper"
    assert session.post.call_count == 2


def test_guest_session_does_not_require_credentials():
    session = MagicMock()
    session.post.return_value = _response({"user": {"id": "guest"}})
    session.get.return_value = _response([{"formatId": "pauper", "displayName": "Pauper"}])

    assert EndstepClient(session=session).resolve_format_id() == "pauper"

    session.post.assert_called_once()


def test_guest_transport_errors_are_wrapped():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("password=dummy-not-a-real-password")
    client = EndstepClient(session=session)

    with pytest.raises(EndstepApiError) as error:
        client.resolve_format_id()

    assert "dummy-not-a-real-password" not in str(error.value)


def test_rejects_changed_leaderboard_contract():
    session = MagicMock()
    session.post.return_value = _response({"user": {"id": "integration"}})
    session.get.return_value = _response({"players": []})
    client = EndstepClient(session=session)

    with pytest.raises(EndstepApiError, match="формат ranked-лидерборда"):
        client.leaderboard(format_id="pauper")


def test_duplicate_exact_username_is_reported_without_failing_other_players():
    session = MagicMock()
    session.post.return_value = _response({"user": {"id": "guest"}})
    session.get.side_effect = [
        _response([{"formatId": "pauper", "displayName": "Pauper"}]),
        _response(
            {
                "rows": [_player("counterspell", rank=613), _player("counterspell", rank=None, provisional=True)],
                "total": 1,
                "provisionalCount": 1,
            }
        ),
        _response({"rows": [_player("Unique")], "total": 1, "provisionalCount": 0}),
    ]

    duplicate, unique = EndstepClient(session=session).find_players(["counterspell", "Unique"])

    assert duplicate.player is None
    assert len(duplicate.exact_matches) == 2
    assert unique.player is not None
    assert len(unique.exact_matches) == 1
