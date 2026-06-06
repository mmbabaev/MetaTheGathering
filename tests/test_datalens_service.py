"""Юнит-тесты сервиса DataLens с замоканным API."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from services.datalens import (
    CHART_IDS,
    Chart,
    DataLensClient,
    DataLensService,
    Period,
    StatRow,
    _parse_row,
    _subtract_months,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _chart_response(rows):
    """Сформировать ответ чарта в формате DataLens из (name, matches, winrate)."""
    return {
        "data": {
            "rows": [
                {"cells": [{"value": name}, {"value": matches}, {"value": winrate}]} for name, matches, winrate in rows
            ]
        }
    }


def _fake_client(responses_by_chart_id):
    """Клиент-заглушка: .run(chart_id, params) отдаёт заранее заданный ответ."""
    client = MagicMock(spec=DataLensClient)

    def run(chart_id, params):
        return responses_by_chart_id[chart_id]

    client.run.side_effect = run
    return client


# ── _subtract_months ─────────────────────────────────────────────────────────


def test_subtract_months_simple():
    assert _subtract_months(date(2026, 6, 6), 2) == date(2026, 4, 6)


def test_subtract_months_crosses_year():
    assert _subtract_months(date(2026, 1, 15), 2) == date(2025, 11, 15)


def test_subtract_months_clamps_day_to_month_length():
    # 31 марта минус 1 месяц → февраль не имеет 31-го числа
    assert _subtract_months(date(2026, 3, 31), 1) == date(2026, 2, 28)


# ── Period ───────────────────────────────────────────────────────────────────


def test_period_all_time():
    assert Period.all_time().raw == "__interval_2023-01-01T00:00:00.000Z___relative_-0d"


def test_period_since():
    assert Period.since(date(2025, 1, 1)).raw == "__interval_2025-01-01T00:00:00.000Z___relative_-0d"


def test_period_last_months_uses_today():
    period = Period.last_months(2, today=date(2026, 6, 6))
    assert period.raw == "__interval_2026-04-06T00:00:00.000Z___relative_-0d"


def test_period_last_days_uses_today():
    period = Period.last_days(10, today=date(2026, 6, 11))
    assert period.raw == "__interval_2026-06-01T00:00:00.000Z___relative_-0d"


# ── _parse_row ───────────────────────────────────────────────────────────────


def test_parse_row_positional_and_rounding():
    row = {"cells": [{"value": "Red Kuldotha"}, {"value": 82}, {"value": 59.14670731}]}
    parsed = _parse_row(row)
    assert parsed == StatRow(name="Red Kuldotha", matches=82, winrate=59.15)


def test_parse_row_coerces_types():
    # API иногда отдаёт числа строками
    row = {"cells": [{"value": "Elves"}, {"value": "8"}, {"value": "25"}]}
    parsed = _parse_row(row)
    assert parsed.matches == 8
    assert parsed.winrate == 25.0


# ── DataLensService: одиночные чарты ─────────────────────────────────────────


def test_player_decks_parses_rows():
    client = _fake_client(
        {CHART_IDS[Chart.DECKS]: _chart_response([("Blue Delver", 75, 53.5), ("Red Burn", 15, 45.5)])}
    )
    service = DataLensService(client)

    decks = service.player_decks("Бабаев Михаил")

    assert [d.name for d in decks] == ["Blue Delver", "Red Burn"]
    assert decks[0].matches == 75


def test_winrate_vs_opponents_uses_opponents_chart():
    client = _fake_client({CHART_IDS[Chart.OPPONENTS]: _chart_response([("Ашаров Вадим", 8, 33.3)])})
    service = DataLensService(client)

    result = service.winrate_vs_opponents("Бабаев Михаил")

    assert result == [StatRow(name="Ашаров Вадим", matches=8, winrate=33.3)]


def test_winrate_vs_opponent_decks_uses_opponent_decks_chart():
    client = _fake_client({CHART_IDS[Chart.OPPONENT_DECKS]: _chart_response([("Grixis Affinity", 31, 50.0)])})
    service = DataLensService(client)

    result = service.winrate_vs_opponent_decks("Бабаев Михаил")

    assert result[0].name == "Grixis Affinity"


def test_service_sends_player_and_period_params():
    client = _fake_client({CHART_IDS[Chart.DECKS]: _chart_response([])})
    service = DataLensService(client)

    service.player_decks("Бабаев Михаил", Period.since(date(2025, 1, 1)))

    chart_id, params = client.run.call_args.args
    assert chart_id == CHART_IDS[Chart.DECKS]
    assert params["igrok_4vy1"] == "Бабаев Михаил"
    assert params["uchastnik_0zyi"] == "Бабаев Михаил"
    assert params["data_v9da"] == "__interval_2025-01-01T00:00:00.000Z___relative_-0d"
    assert params["klub_77wt"] == ""


def test_service_empty_response_returns_empty_list():
    client = _fake_client({CHART_IDS[Chart.DECKS]: {"data": {"rows": []}}})
    service = DataLensService(client)

    assert service.player_decks("Кто-то") == []


def test_service_missing_data_key_returns_empty_list():
    client = _fake_client({CHART_IDS[Chart.DECKS]: {}})
    service = DataLensService(client)

    assert service.player_decks("Кто-то") == []


# ── DataLensService.player_report ────────────────────────────────────────────


def test_player_report_all_charts():
    client = _fake_client(
        {
            CHART_IDS[Chart.DECKS]: _chart_response([("Blue Delver", 75, 53.5)]),
            CHART_IDS[Chart.OPPONENTS]: _chart_response([("Ашаров Вадим", 8, 33.3)]),
            CHART_IDS[Chart.OPPONENT_DECKS]: _chart_response([("Elves", 8, 25.0)]),
        }
    )
    service = DataLensService(client)

    report = service.player_report("Бабаев Михаил")

    assert report.player == "Бабаев Михаил"
    assert report.decks[0].name == "Blue Delver"
    assert report.opponents[0].name == "Ашаров Вадим"
    assert report.opponent_decks[0].name == "Elves"
    assert client.run.call_count == 3


def test_player_report_subset_of_charts():
    client = _fake_client({CHART_IDS[Chart.DECKS]: _chart_response([("Blue Delver", 75, 53.5)])})
    service = DataLensService(client)

    report = service.player_report("Бабаев Михаил", charts=[Chart.DECKS])

    assert report.decks is not None
    assert report.opponents is None
    assert report.opponent_decks is None
    assert client.run.call_count == 1


# ── DataLensService.scout_opponent ───────────────────────────────────────────


def test_scout_opponent_returns_decks_and_head_to_head():
    client = _fake_client(
        {
            CHART_IDS[Chart.DECKS]: _chart_response([("Flicker Tron", 49, 67.3)]),
            CHART_IDS[Chart.OPPONENTS]: _chart_response([("Гусаров Антон", 13, 75.6), ("Ашаров Вадим", 8, 33.3)]),
        }
    )
    service = DataLensService(client)

    scouting = service.scout_opponent("Бабаев Михаил", "Ашаров Вадим")

    assert scouting.player == "Бабаев Михаил"
    assert scouting.opponent == "Ашаров Вадим"
    assert scouting.opponent_decks[0].name == "Flicker Tron"
    assert scouting.head_to_head == StatRow(name="Ашаров Вадим", matches=8, winrate=33.3)


def test_scout_opponent_head_to_head_none_when_no_matches():
    client = _fake_client(
        {
            CHART_IDS[Chart.DECKS]: _chart_response([("Flicker Tron", 49, 67.3)]),
            CHART_IDS[Chart.OPPONENTS]: _chart_response([("Гусаров Антон", 13, 75.6)]),
        }
    )
    service = DataLensService(client)

    scouting = service.scout_opponent("Бабаев Михаил", "Незнакомец")

    assert scouting.head_to_head is None
    assert scouting.opponent_decks  # колоды оппонента всё равно вернулись


def test_scout_opponent_default_periods():
    client = _fake_client(
        {
            CHART_IDS[Chart.DECKS]: _chart_response([]),
            CHART_IDS[Chart.OPPONENTS]: _chart_response([]),
        }
    )
    service = DataLensService(client)

    service.scout_opponent("Бабаев Михаил", "Ашаров Вадим")

    periods_by_chart = {chart_id: params["data_v9da"] for (chart_id, params), _ in client.run.call_args_list}
    # колоды оппонента — фиксированный период (не all-time), H2H — all-time
    assert periods_by_chart[CHART_IDS[Chart.DECKS]] != Period.all_time().raw
    assert periods_by_chart[CHART_IDS[Chart.OPPONENTS]] == Period.all_time().raw


# ── DataLensClient (HTTP-слой) ───────────────────────────────────────────────


def _mock_session(json_payload):
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = json_payload
    session.post.return_value = response
    return session, response


def test_client_run_builds_payload_and_headers():
    session, _ = _mock_session(_chart_response([("Blue Delver", 75, 53.5)]))
    client = DataLensClient(session=session, dash_id="dash123", dash_tab_id="Za")

    result = client.run("chartXYZ", {"igrok_4vy1": "Бабаев Михаил"})

    assert result["data"]["rows"]
    url, kwargs = session.post.call_args.args[0], session.post.call_args.kwargs
    assert url == "https://datalens.yandex/charts/api/run"
    payload = kwargs["json"]
    assert payload["id"] == "chartXYZ"
    assert payload["params"] == {"igrok_4vy1": "Бабаев Михаил"}
    headers = kwargs["headers"]
    assert headers["x-dash-info"] == "dashIddash123dashTabIdZa"
    assert headers["Referer"] == "https://datalens.yandex/dash123"


def test_client_run_raises_for_status_error():
    session, response = _mock_session({})
    response.raise_for_status.side_effect = RuntimeError("HTTP 500")
    client = DataLensClient(session=session)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        client.run("chartXYZ", {})
