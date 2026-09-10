from datetime import datetime
from unittest.mock import MagicMock

from bot.handlers.endstep_leaderboard import ENDSTEP_RU_PAGE_SIZE, EndstepRuLeaderboardHandler
from bot.keyboards import CB_ENDSTEP_RU_PAGE, CB_ENDSTEP_RU_REFRESH
from services.endstep import EndstepApiError, EndstepConfigurationError
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardRow

OWNER_ID = 9200


def _snapshot(size: int, *, missing: tuple[str, ...] = ()) -> EndstepRuLeaderboard:
    return EndstepRuLeaderboard(
        generated_at=datetime(2026, 9, 10),
        candidate_count=size + len(missing),
        rows=tuple(
            EndstepRuLeaderboardRow(
                position=index,
                user_id=index,
                username=f"Player{index:02d}",
                site_rank=index * 3 if index < size else None,
                rating=1701 - index,
                rd=70,
                wins=10,
                losses=4,
                draws=1,
                provisional=index == size,
            )
            for index in range(1, size + 1)
        ),
        missing_usernames=missing,
    )


def _callbacks(result):
    return [button.callback_data for row in result.keyboard.inline_keyboard for button in row]


def test_non_owner_cannot_trigger_external_lookup(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    service = MagicMock()

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID + 1)

    assert loaded.snapshot is None
    assert loaded.result.is_alert is True
    assert "только владельцу" in loaded.result.text
    service.calculate.assert_not_called()


def test_pages_show_ru_and_site_positions(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    snapshot = _snapshot(11, missing=("WrongNick",))
    handler = EndstepRuLeaderboardHandler()

    first = handler.render(OWNER_ID, snapshot, 0)
    second = handler.render(OWNER_ID, snapshot, 1)

    assert "1. Player01 — сайт #3 · 1700 ±70 · 10–4–1" in first.text
    assert "10. Player10" in first.text
    assert "11. Player11 — сайт без места" not in first.text
    assert "11. Player11 — сайт без места" in second.text
    assert "provisional" in second.text
    assert "Не найдены: WrongNick" in second.text
    assert "Страница 2/2" in second.text
    assert f"{CB_ENDSTEP_RU_PAGE}:0" in _callbacks(second)
    assert CB_ENDSTEP_RU_REFRESH in _callbacks(second)
    assert ENDSTEP_RU_PAGE_SIZE == 10


def test_load_returns_snapshot_for_callback_cache(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    service = MagicMock()
    service.calculate.return_value = _snapshot(2)

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID)

    assert loaded.snapshot is service.calculate.return_value
    assert "найдено 2 из 2" in loaded.result.text


def test_missing_credentials_are_explained_without_call_details(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    service = MagicMock()
    service.calculate.side_effect = EndstepConfigurationError("internal detail")

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID)

    assert loaded.snapshot is None
    assert "ENDSTEP_API_USERNAME" in loaded.result.text
    assert "internal detail" not in loaded.result.text
    assert _callbacks(loaded.result) == [CB_ENDSTEP_RU_REFRESH]


def test_api_error_is_safe_and_refresh_remains_available(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    service = MagicMock()
    service.calculate.side_effect = EndstepApiError("Endstep временно ограничил частоту запросов")

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID)

    assert loaded.snapshot is None
    assert "временно ограничил" in loaded.result.text
    assert _callbacks(loaded.result) == [CB_ENDSTEP_RU_REFRESH]


def test_empty_roster_has_owner_only_refresh_button(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    result = EndstepRuLeaderboardHandler().render(OWNER_ID, _snapshot(0))

    assert "нет игроков с заполненным Endstep-ником" in result.text
    assert _callbacks(result) == [CB_ENDSTEP_RU_REFRESH]
