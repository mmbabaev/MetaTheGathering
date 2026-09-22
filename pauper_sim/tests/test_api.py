from pathlib import Path

import pytest
from fastapi import HTTPException

import pauper_sim.app as app_module
from pauper_sim.app import (
    PairIn,
    RollIn,
    api_pair,
    api_roll,
    api_winrates,
    api_winrates_refresh,
    index,
)
from pauper_sim.winrates import parse_winrates

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def winrate_data():
    return parse_winrates((FIXTURES / "winrates.html").read_text(encoding="utf-8"), fetched_at=1.0)


class _DummyCache:
    def __init__(self, data) -> None:
        self._data = data

    def get(self, *, force: bool = False):
        return self._data


@pytest.fixture()
def patch_cache(monkeypatch, winrate_data):
    monkeypatch.setattr(app_module, "_winrate_cache", _DummyCache(winrate_data))


def test_index_serves_frontend() -> None:
    response = index()
    assert Path(response.path).name == "index.html"


def test_api_winrates_serialized(patch_cache) -> None:
    payload = api_winrates()
    assert payload["pool_size"] == 20
    assert payload["decks"][0]["name"] == "Mono Red Madness"
    assert payload["matrix"]["Mono Red Madness"]["Grixis Affinity"] == 43


def test_api_winrates_refresh(monkeypatch, winrate_data) -> None:
    monkeypatch.setattr(app_module, "_winrate_cache", _DummyCache(winrate_data))
    payload = api_winrates_refresh()
    assert payload["decks"][0]["matches"] == 7568


def test_api_roll_returns_winner_and_probability(patch_cache) -> None:
    result = api_roll(RollIn(a="Mono Red Madness", b="Grixis Affinity"))
    assert result["winner"] in {"a", "b"}
    assert result["probability_pct"] == 43.0


def test_api_pair_even(patch_cache) -> None:
    result = api_pair(
        PairIn(
            players=[
                {"name": "Вася", "deck": "Mono Red Madness"},
                {"name": "Петя", "deck": "Grixis Affinity"},
                {"name": "Ира", "deck": "Elves"},
                {"name": "Леша", "deck": "Elves"},
            ]
        )
    )
    assert len(result["matches"]) == 2
    assert result["bye"] is None
    assert result["matches"][0]["a"]["name"] in {"Вася", "Петя", "Ира", "Леша"}


def test_api_pair_odd_bye(patch_cache) -> None:
    players = [{"name": f"P{i}", "deck": "Mono Red Madness"} for i in range(5)]
    result = api_pair(PairIn(players=players))
    assert len(result["matches"]) == 2
    assert result["bye"] is not None


def test_api_pair_requires_two_players(patch_cache) -> None:
    with pytest.raises(HTTPException) as exc:
        api_pair(PairIn(players=[{"name": "Один", "deck": "Elves"}]))
    assert exc.value.status_code == 400


def test_api_winrates_returns_502_on_fetch_failure(monkeypatch) -> None:
    class _Boom:
        def get(self, *, force: bool = False):
            raise RuntimeError("blocked by Cloudflare")

    monkeypatch.setattr(app_module, "_winrate_cache", _Boom())
    with pytest.raises(HTTPException) as exc:
        api_winrates()
    assert exc.value.status_code == 502
