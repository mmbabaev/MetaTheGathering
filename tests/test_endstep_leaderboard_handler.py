from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

from bot.handlers.endstep_leaderboard import ENDSTEP_RU_PAGE_SIZE, EndstepRuLeaderboardHandler
from bot.keyboards import CB_ENDSTEP_RU_ME, CB_ENDSTEP_RU_PAGE, CB_LEADERBOARD_MENU
from services.endstep_ru_leaderboard import EndstepRuLeaderboard, EndstepRuLeaderboardRow

OWNER_ID = 9200


def _snapshot(
    size: int,
    *,
    missing: tuple[str, ...] = (),
    ambiguous: tuple[str, ...] = (),
) -> EndstepRuLeaderboard:
    return EndstepRuLeaderboard(
        generated_at=datetime(2026, 9, 10),
        candidate_count=size + len(missing) + len(ambiguous),
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
        ambiguous_usernames=ambiguous,
    )


def _callbacks(result):
    return [button.callback_data for row in result.keyboard.inline_keyboard for button in row]


def test_any_player_can_read_local_snapshot():
    service = MagicMock()
    service.latest.return_value = _snapshot(1)

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID + 1)

    assert loaded.snapshot is service.latest.return_value
    assert loaded.result.is_alert is False
    assert "Player01" in loaded.result.text


def test_pages_show_readable_player_cards_with_ru_and_site_positions():
    snapshot = _snapshot(11, missing=("WrongNick",), ambiguous=("counterspell",))
    handler = EndstepRuLeaderboardHandler()

    first = handler.render(OWNER_ID, snapshot, 0)
    second = handler.render(OWNER_ID, snapshot, 1)

    assert "<b>1. Player01</b>" in first.text
    assert "сайт #3 · 1700 (RD 70) · 10–4–1" in first.text
    assert "<b>10. Player10</b>" in first.text
    assert "11. Player11" not in first.text
    assert "<b>11. Player11</b>" in second.text
    assert "сайт —* · 1690 (RD 70) · 10–4–1" in second.text
    assert "provisional" in second.text
    assert "RD — отклонение рейтинга" in second.text
    assert "WrongNick" not in second.text
    assert "counterspell" not in second.text
    assert "Страница 2/2" in second.text
    assert f"{CB_ENDSTEP_RU_PAGE}:0" in _callbacks(second)
    assert CB_ENDSTEP_RU_ME in _callbacks(second)
    assert CB_LEADERBOARD_MENU in _callbacks(second)
    assert ENDSTEP_RU_PAGE_SIZE == 10
    assert first.parse_mode == "HTML"


def test_load_returns_snapshot_for_callback_cache():
    service = MagicMock()
    service.latest.return_value = _snapshot(2)

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID)

    assert loaded.snapshot is service.latest.return_value
    assert "игроков: 2" in loaded.result.text
    assert "Обновлено 10.09.2026 03:00 МСК" in loaded.result.text


def test_missing_local_snapshot_is_explained():
    service = MagicMock()
    service.latest.return_value = None

    loaded = EndstepRuLeaderboardHandler(service).load(OWNER_ID)

    assert loaded.snapshot is None
    assert "ещё не обновлялся" in loaded.result.text
    assert _callbacks(loaded.result) == [CB_ENDSTEP_RU_ME, CB_LEADERBOARD_MENU]


def test_empty_roster_has_menu_back_button():
    result = EndstepRuLeaderboardHandler().render(OWNER_ID, _snapshot(0))

    assert "нет игроков с заполненным Endstep-ником" in result.text
    assert _callbacks(result) == [CB_ENDSTEP_RU_ME, CB_LEADERBOARD_MENU]


def test_player_cards_escape_endstep_usernames():
    snapshot = _snapshot(1, missing=("<missing>",), ambiguous=("same&name",))
    snapshot = replace(snapshot, rows=(replace(snapshot.rows[0], username="<player&one>"),))

    result = EndstepRuLeaderboardHandler().render(OWNER_ID, snapshot)

    assert "&lt;player&amp;one&gt;" in result.text
    assert "&lt;missing&gt;" not in result.text
    assert "same&amp;name" not in result.text
    assert "<player&one>" not in result.text


def test_owner_keeps_mapping_diagnostics(monkeypatch):
    monkeypatch.setattr("bot.handlers.endstep_leaderboard.settings.OWNER_CHAT_ID", OWNER_ID)
    snapshot = _snapshot(1, missing=("<missing>",), ambiguous=("same&name",))

    result = EndstepRuLeaderboardHandler().render(OWNER_ID, snapshot)

    assert "Не найдены: &lt;missing&gt;" in result.text
    assert "Несколько аккаунтов с этим ником: same&amp;name" in result.text


def test_where_am_i_opens_players_page_and_highlights_row():
    service = MagicMock()
    service.latest.return_value = _snapshot(14)
    users = MagicMock()
    users.get_by_tg_id.return_value = MagicMock(id=12)

    loaded = EndstepRuLeaderboardHandler(service, users).load_me(OWNER_ID)

    assert loaded.snapshot is service.latest.return_value
    assert "👉 <b>12. Player12</b>" in loaded.result.text
    assert "Страница 2/2" in loaded.result.text
    assert CB_ENDSTEP_RU_ME not in _callbacks(loaded.result)
    assert f"{CB_ENDSTEP_RU_PAGE}:0" in _callbacks(loaded.result)


def test_where_am_i_explains_how_to_join_when_player_is_missing():
    service = MagicMock()
    service.latest.return_value = _snapshot(2)
    users = MagicMock()
    users.get_by_tg_id.return_value = MagicMock(id=99)

    loaded = EndstepRuLeaderboardHandler(service, users).load_me(OWNER_ID)

    assert "Тебя пока нет" in loaded.result.text
    assert "Endstep-ник" in loaded.result.text
    assert _callbacks(loaded.result) == [f"{CB_ENDSTEP_RU_PAGE}:0"]
