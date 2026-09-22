import json
import time
from pathlib import Path

import pytest

from pauper_sim.winrates import (
    WinrateCache,
    from_dict,
    parse_winrates,
    to_dict,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html() -> str:
    return (FIXTURES / "winrates.html").read_text(encoding="utf-8")


def test_parse_decks_and_matrix() -> None:
    data = parse_winrates(fixture_html(), fetched_at=123.0)

    assert [deck.name for deck in data.decks] == [
        "Mono Red Madness",
        "Grixis Affinity",
        "Mono Blue Terror",
        "Jund Wildfire",
        "Elves",
        "Mono Red Burn",
        "Persistent Petitioners",
    ]
    assert data.decks[0].overall_winrate == 51.0
    assert data.decks[0].matches == 7568
    assert data.decks[4].overall_winrate == 50.0
    assert data.fetched_at == 123.0

    assert data.winrate_against("Mono Red Madness", "Grixis Affinity") == 43
    assert data.winrate_against("Grixis Affinity", "Mono Red Madness") == 57
    assert data.winrate_against("Mono Red Madness", "Elves") == 77
    assert data.winrate_against("Elves", "Mono Red Madness") == 23


def test_parse_rows_with_fewer_cells() -> None:
    data = parse_winrates(fixture_html(), fetched_at=1.0)
    assert data.winrate_against("Mono Red Burn", "Mono Red Madness") == 45
    assert data.winrate_against("Mono Red Burn", "Jund Wildfire") is None
    assert data.winrate_against("Persistent Petitioners", "Elves") is None


def test_parse_raises_when_table_missing() -> None:
    with pytest.raises(ValueError, match="winrates table not found"):
        parse_winrates("<html><body>no table here</body></html>")


def test_to_from_dict_roundtrip() -> None:
    data = parse_winrates(fixture_html(), fetched_at=123.0)
    restored = from_dict(to_dict(data))
    assert restored == data


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _bundled_data() -> dict:
    return to_dict(parse_winrates(fixture_html(), fetched_at=time.time() - 10_000))


def test_cache_serves_bundled_when_network_down(tmp_path, monkeypatch) -> None:
    bundled = tmp_path / "snapshot.json"
    _write_json(bundled, _bundled_data())

    def boom() -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", boom)
    cache = WinrateCache(
        ttl_seconds=3600,
        persist_path=tmp_path / "cache.json",
        bundled_path=bundled,
    )
    data = cache.get()
    assert data.decks[0].name == "Mono Red Madness"


def test_cache_persists_successful_fetch(tmp_path, monkeypatch) -> None:
    persist = tmp_path / "cache.json"
    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", fixture_html)

    cache = WinrateCache(ttl_seconds=3600, persist_path=persist, bundled_path=None)
    cache.get()
    assert persist.exists()
    saved = json.loads(persist.read_text(encoding="utf-8"))
    assert saved["decks"][0]["name"] == "Mono Red Madness"

    def boom() -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", boom)
    second = WinrateCache(ttl_seconds=3600, persist_path=persist, bundled_path=None)
    assert second.get().decks[0].name == "Mono Red Madness"


def test_cache_raises_when_no_source_available(tmp_path, monkeypatch) -> None:
    def boom() -> str:
        raise RuntimeError("network down")

    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", boom)
    cache = WinrateCache(ttl_seconds=3600, persist_path=tmp_path / "x.json", bundled_path=None)
    with pytest.raises(RuntimeError, match="network down"):
        cache.get()


def test_cache_uses_fresh_memory_without_fetch(tmp_path, monkeypatch) -> None:
    def boom() -> str:
        raise AssertionError("fetch should not be called")

    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", boom)
    cache = WinrateCache(ttl_seconds=3600, persist_path=tmp_path / "x.json", bundled_path=None)
    cache._data = parse_winrates(fixture_html(), fetched_at=time.time())
    assert cache.get().decks[0].name == "Mono Red Madness"


def test_cache_force_refresh_replaces_old_data(tmp_path, monkeypatch) -> None:
    bundled = tmp_path / "snapshot.json"
    _write_json(bundled, to_dict(parse_winrates(fixture_html(), fetched_at=1.0)))
    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", fixture_html)
    cache = WinrateCache(ttl_seconds=3600, persist_path=tmp_path / "c.json", bundled_path=bundled)
    cache.get()
    monkeypatch.setattr("pauper_sim.winrates.fetch_winrates_html", lambda: fixture_html() + "")
    fresh = parse_winrates(fixture_html(), fetched_at=999.0)
    monkeypatch.setattr("pauper_sim.winrates.parse_winrates", lambda html, fetched_at=None: fresh)
    assert cache.get(force=True).fetched_at == 999.0
