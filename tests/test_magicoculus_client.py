from datetime import date
from unittest.mock import MagicMock, call

import pytest

from services.magicoculus import (
    MagicOculusApiError,
    MagicOculusClient,
    MagicOculusPlayerDeck,
    MagicOculusTournament,
)


def _response(body, *, status=200):
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def _tournament():
    return MagicOculusTournament(
        source_tournament_id=42,
        date=date(2026, 7, 24),
        club="Goldfish",
        aetherhub_url="https://aetherhub.com/Tourney/RoundTourney/42",
        player_decks=[MagicOculusPlayerDeck(player="Иванов Иван", deck="Elves", final_place=1)],
    )


def test_resolves_current_reference_ids():
    session = MagicMock()
    session.get.side_effect = [
        _response([{"id": "moscow", "name": "Москва"}]),
        _response([{"id": "goldfish_moscow", "name": "Goldfish"}]),
        _response([{"id": "pauper", "name": "Pauper"}]),
    ]

    result = MagicOculusClient("https://magic.example", session=session).resolve_reference_ids(
        city="москва", club="goldfish", format_name="pauper"
    )

    assert result == ("moscow", "goldfish_moscow", "pauper")
    assert session.get.call_args_list == [
        call("https://magic.example/api/v1/cities", timeout=30),
        call("https://magic.example/api/v1/cities/moscow/clubs", timeout=30),
        call("https://magic.example/api/v1/formats", timeout=30),
    ]


def test_maps_bot_club_name_to_magic_oculus_reference():
    session = MagicMock()
    session.get.side_effect = [
        _response([{"id": "moscow", "name": "Москва"}]),
        _response([{"id": "edinorog_moscow", "name": "Единорог"}]),
        _response([{"id": "pauper", "name": "Pauper"}]),
    ]

    result = MagicOculusClient("https://magic.example", session=session).resolve_reference_ids(
        city="Москва", club="Edinorog", format_name="Pauper"
    )

    assert result == ("moscow", "edinorog_moscow", "pauper")


def test_existing_daily_keys_reads_all_pages_and_skips_bad_rows():
    session = MagicMock()
    session.get.side_effect = [
        _response(
            {
                "next": "page-2",
                "results": [
                    {
                        "id": 145,
                        "date": "2026-07-20",
                        "type": "daily",
                        "club": {"name": "Единорог"},
                        "format": {"name": "Pauper"},
                    },
                    {"id": 999, "type": "tournament"},
                ],
            }
        ),
        _response(
            {
                "next": None,
                "results": [
                    {
                        "id": 146,
                        "date": "2026-07-24",
                        "type": "daily",
                        "club": {"name": "Goldfish"},
                        "format": {"name": "Pauper"},
                    },
                    {"id": "bad", "date": "bad", "type": "daily", "club": {}, "format": {}},
                ],
            }
        ),
    ]

    result = MagicOculusClient("https://magic.example", session=session).existing_daily_keys()

    assert result == {
        (date(2026, 7, 20), "единорог", "pauper"): 145,
        (date(2026, 7, 24), "goldfish", "pauper"): 146,
    }
    assert session.get.call_args_list == [
        call("https://magic.example/api/v1/tournaments?page=1", timeout=30),
        call("https://magic.example/api/v1/tournaments?page=2", timeout=30),
    ]


def test_reference_must_have_exactly_one_match():
    session = MagicMock()
    session.get.return_value = _response([])

    with pytest.raises(MagicOculusApiError, match="найдено 0"):
        MagicOculusClient("https://magic.example", session=session).resolve_reference_ids(
            city="Москва", club="Goldfish", format_name="Pauper"
        )


def test_imports_multipart_and_verifies_detail():
    session = MagicMock()
    session.post.return_value = _response(
        {
            "success": True,
            "tournament": {"id": 145},
            "warnings": [{"code": "PLAYER_NAME_NORMALIZED", "message": "Имя нормализовано"}],
        }
    )
    session.get.return_value = _response({"id": 145, "standings": [{"place": 1}]})

    result = MagicOculusClient("https://magic.example/", session=session).import_tournament(
        _tournament(), city_id="moscow", club_id="goldfish_moscow", format_id="pauper"
    )

    assert result.tournament_id == 145
    assert result.warnings[0].code == "PLAYER_NAME_NORMALIZED"
    assert result.detail["standings"][0]["place"] == 1
    files = session.post.call_args.kwargs["files"]
    assert files["date"] == (None, "2026-07-24")
    assert files["playerDecksText"] == (None, "Elves")
    session.get.assert_called_once_with("https://magic.example/api/v1/tournaments/145", timeout=30)


def test_preserves_all_api_errors_in_exception():
    session = MagicMock()
    session.post.return_value = _response(
        {
            "success": False,
            "errors": [
                {"code": "FIRST", "message": "Первая"},
                {"code": "SECOND", "message": "Вторая"},
            ],
        },
        status=422,
    )

    with pytest.raises(MagicOculusApiError) as error:
        MagicOculusClient("https://magic.example", session=session).import_tournament(
            _tournament(), city_id="moscow", club_id="goldfish_moscow", format_id="pauper"
        )

    assert "FIRST: Первая" in str(error.value)
    assert "SECOND: Вторая" in str(error.value)
    session.get.assert_not_called()
