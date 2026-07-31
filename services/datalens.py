"""Сервис чтения личной статистики игрока из дашборда Yandex DataLens.

Дашборд «Личная статистика» (dashId ``6dr39r9a9l9mt``) публичный — запросы идут
анонимно, без cookie. Под капотом каждый виджет — это «чарт», который дёргается
через ``POST https://datalens.yandex/charts/api/run`` с параметрами селекторов
(игрок + период). Все три используемых чарта возвращают единообразную таблицу из
трёх колонок ``[имя, матчей, winrate]``, поэтому парсер один на всех.

Пример::

    service = DataLensService()
    report = service.player_report("Бабаев Михаил", Period.last_months(2))
    for deck in report.decks:
        print(deck.name, deck.matches, deck.winrate)
"""

from __future__ import annotations

import calendar
import copy
import json
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Optional

import requests
from pydantic import BaseModel

DATALENS_URL = "https://datalens.yandex/charts/api/run"
DATALENS_PUBLIC_ENTRY_URL = "https://datalens.yandex/gateway/root/us/getPublicEntry"
DASH_ID = "6dr39r9a9l9mt"
DASH_TAB_ID = "Za"

# Самая ранняя дата лиги — используется как «начало времён» для all-time.
_EPOCH = "2023-01-01T00:00:00.000Z"


class Chart(str, Enum):
    """Виджеты дашборда, которые умеет читать сервис."""

    DECKS = "decks"  # «Декчойс» — колоды самого игрока
    OPPONENTS = "opponents"  # «Оппонент и винрейт против него»
    OPPONENT_DECKS = "opponent_decks"  # «Винрейт против дек оппонентов»


# id чартов внутри дашборда (см. getPublicEntry → data.tabs[].items[].data.tabs[])
CHART_IDS: dict[Chart, str] = {
    Chart.DECKS: "jsaobu3lpeos6",
    Chart.OPPONENTS: "z8rami53rgu0m",
    Chart.OPPONENT_DECKS: "en6q8x8cdhs61",
}

TOURNAMENT_CHART_ID = "47cz6kdjt7cer"
TOURNAMENT_DATASET_ID = "hkp5eiu66low4"
TOURNAMENT_FIELDS = {
    "date": ("turniry_cr5j", "Турниры", "date"),
    "place": ("mesto_z8fl", "Место", "integer"),
    "player": ("uchastnik_0zyi", "Участник", "string"),
    "deck": ("koloda_q1gh", "Колода", "string"),
    "club": ("klub_a9uu", "Клуб", "string"),
}


@dataclass(frozen=True)
class Period:
    """Период для фильтра ``data_v9da``.

    DataLens в публичном режиме принимает интервал вида
    ``__interval_<ISO>___relative_-0d`` (от абсолютной даты до «сейчас»).
    Интервал из двух абсолютных дат возвращает ошибку, а голый relative
    (``-2M``) не фильтрует — поэтому всегда фиксируем начало даты.
    """

    raw: str

    @classmethod
    def all_time(cls) -> "Period":
        return cls(f"__interval_{_EPOCH}___relative_-0d")

    @classmethod
    def since(cls, start: date) -> "Period":
        return cls(f"__interval_{start:%Y-%m-%d}T00:00:00.000Z___relative_-0d")

    @classmethod
    def last_months(cls, months: int, *, today: Optional[date] = None) -> "Period":
        today = today or date.today()
        return cls.since(_subtract_months(today, months))

    @classmethod
    def last_days(cls, days: int, *, today: Optional[date] = None) -> "Period":
        today = today or date.today()
        return cls.since(today - timedelta(days=days))


class StatRow(BaseModel):
    """Одна строка таблицы чарта: сущность + матчи + винрейт (%)."""

    name: str
    matches: int
    winrate: float


class PlayerReport(BaseModel):
    """Сводка по игроку. Заполняются только запрошенные чарты."""

    player: str
    period: str
    decks: Optional[list[StatRow]] = None
    opponents: Optional[list[StatRow]] = None
    opponent_decks: Optional[list[StatRow]] = None


class OpponentScouting(BaseModel):
    """Подготовка к матчу против конкретного оппонента.

    ``opponent_decks`` — на чём оппонент играл в указанный период (его декчойс),
    ``head_to_head`` — мой винрейт лично против него (None, если матчей не было).
    """

    player: str
    opponent: str
    decks_period: str
    head_to_head_period: str
    opponent_decks: list[StatRow]
    head_to_head: Optional[StatRow] = None


class TournamentPlayer(BaseModel):
    place: int
    player: str
    deck: str


class DataLensTournament(BaseModel):
    date: date
    club: str
    format: str = "Pauper"
    players: list[TournamentPlayer]


class DataLensTournamentError(ValueError):
    pass


def _subtract_months(d: date, months: int) -> date:
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_row(row: dict) -> StatRow:
    """Все три чарта отдают колонки в порядке [имя, матчей, winrate]."""
    cells = row["cells"]
    return StatRow(
        name=cells[0]["value"],
        matches=int(cells[1]["value"]),
        winrate=round(float(cells[2]["value"]), 2),
    )


class DataLensClient:
    """Тонкий HTTP-клиент к ``charts/api/run``.

    ``session`` инжектируется снаружи — это позволяет подменить транспорт
    (например, добавить прокси) в тестах и в боте.
    """

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        base_url: str = DATALENS_URL,
        dash_id: str = DASH_ID,
        dash_tab_id: str = DASH_TAB_ID,
        timeout: int = 30,
    ) -> None:
        self._session = session or requests.Session()
        self._url = base_url
        self._dash_id = dash_id
        self._dash_tab_id = dash_tab_id
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain",
            "Origin": "https://datalens.yandex",
            "Referer": f"https://datalens.yandex/{self._dash_id}",
            "x-dl-component": "ui",
            "x-dl-display-mode": "basic",
            "x-dash-info": f"dashId{self._dash_id}dashTabId{self._dash_tab_id}",
        }

    def run(self, chart_id: str, params: dict) -> dict:
        """Выполнить чарт и вернуть распарсенный JSON-ответ целиком."""
        payload = {
            "id": chart_id,
            "params": params,
            "widgetConfig": {"actionParams": {"enable": True}},
            "responseOptions": {"includeConfig": False, "includeLogs": False},
        }
        response = self._session.post(self._url, json=payload, headers=self._headers(), timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def public_entry(self, entry_id: str) -> dict:
        response = self._session.post(
            DATALENS_PUBLIC_ENTRY_URL,
            json={"entryId": entry_id},
            headers=self._headers(),
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def run_config(self, chart_id: str, shared: dict, params: dict) -> dict:
        """Run an unsaved chart configuration without modifying the public dashboard."""
        payload = {
            "id": chart_id,
            "params": params,
            "config": {
                "data": {"shared": json.dumps(shared, ensure_ascii=False)},
                "meta": {"stype": "graph_wizard_node"},
            },
            "responseOptions": {"includeConfig": False, "includeLogs": False},
        }
        response = self._session.post(self._url, json=payload, headers=self._headers(), timeout=self._timeout)
        response.raise_for_status()
        return response.json()


class DataLensService:
    """Высокоуровневый доступ к личной статистике игрока."""

    def __init__(self, client: Optional[DataLensClient] = None) -> None:
        self._client = client or DataLensClient()

    def _rows(self, chart: Chart, player: str, period: Period) -> list[StatRow]:
        response = self._client.run(
            CHART_IDS[chart],
            {
                "klub_77wt": "",  # фильтр по турниру; пусто = все
                "data_v9da": period.raw,
                "igrok_4vy1": player,
                "uchastnik_0zyi": player,
            },
        )
        rows = response.get("data", {}).get("rows", [])
        return [_parse_row(row) for row in rows]

    def player_decks(self, player: str, period: Optional[Period] = None) -> list[StatRow]:
        """Колоды игрока: архетип, сыгранные матчи, винрейт."""
        return self._rows(Chart.DECKS, player, period or Period.all_time())

    def winrate_vs_opponents(self, player: str, period: Optional[Period] = None) -> list[StatRow]:
        """Винрейт игрока против каждого оппонента (по имени)."""
        return self._rows(Chart.OPPONENTS, player, period or Period.all_time())

    def winrate_vs_opponent_decks(self, player: str, period: Optional[Period] = None) -> list[StatRow]:
        """Винрейт игрока против архетипов колод оппонентов."""
        return self._rows(Chart.OPPONENT_DECKS, player, period or Period.all_time())

    def scout_opponent(
        self,
        player: str,
        opponent: str,
        *,
        decks_period: Optional[Period] = None,
        head_to_head_period: Optional[Period] = None,
    ) -> OpponentScouting:
        """Сводка для подготовки к матчу ``player`` против ``opponent``.

        По умолчанию: колоды оппонента за последние 3 месяца + мой личный
        винрейт против него за всё время.
        """
        decks_period = decks_period or Period.last_months(3)
        head_to_head_period = head_to_head_period or Period.all_time()

        opponent_decks = self.player_decks(opponent, decks_period)
        my_opponents = self.winrate_vs_opponents(player, head_to_head_period)
        head_to_head = next((row for row in my_opponents if row.name == opponent), None)

        return OpponentScouting(
            player=player,
            opponent=opponent,
            decks_period=decks_period.raw,
            head_to_head_period=head_to_head_period.raw,
            opponent_decks=opponent_decks,
            head_to_head=head_to_head,
        )

    def player_report(
        self,
        player: str,
        period: Optional[Period] = None,
        charts: Iterable[Chart] = tuple(Chart),
    ) -> PlayerReport:
        """Собрать сводку по игроку по выбранным чартам.

        ``charts`` управляет тем, какие виджеты запрашивать — по умолчанию все три.
        """
        period = period or Period.all_time()
        report = PlayerReport(player=player, period=period.raw)
        for chart in charts:
            setattr(report, chart.value, self._rows(chart, player, period))
        return report

    @staticmethod
    def _tournament_table_config(shared: dict) -> dict:
        shared = copy.deepcopy(shared)
        items = []
        for guid, title, data_type in TOURNAMENT_FIELDS.values():
            items.append(
                {
                    "guid": guid,
                    "title": title,
                    "type": "DIMENSION",
                    "cast": data_type,
                    "data_type": data_type,
                    "initial_data_type": data_type,
                    "datasetId": TOURNAMENT_DATASET_ID,
                    "aggregation": "none",
                    "managed_by": "user",
                    "valid": True,
                    "virtual": False,
                    "hidden": False,
                    "autoaggregated": False,
                    "has_auto_aggregation": False,
                    "lock_aggregation": False,
                    "aggregation_locked": False,
                    "calc_mode": "direct",
                }
            )
        shared["visualization"] = {
            "id": "flatTable",
            "type": "table",
            "name": "label_visualization-flat-table",
            "allowFilters": True,
            "allowColors": True,
            "allowSort": True,
            "placeholders": [
                {
                    "id": "flat-table-columns",
                    "type": "flat-table-columns",
                    "title": "section_columns",
                    "items": items,
                    "required": True,
                    "settings": {"groupping": "on"},
                }
            ],
        }
        shared["colors"] = []
        shared["labels"] = []
        shared["sort"] = []
        shared["filters"] = []
        return shared

    def tournament(self, event_date: date, *, club: str | None = None) -> DataLensTournament:
        """Return final places and decks for one Pauper daily from DataLens."""
        entry = self._client.public_entry(TOURNAMENT_CHART_ID)
        try:
            shared = json.loads(entry["data"]["shared"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DataLensTournamentError("DataLens не вернул конфигурацию чарта дейликов") from exc

        response = self._client.run_config(
            TOURNAMENT_CHART_ID,
            self._tournament_table_config(shared),
            {TOURNAMENT_FIELDS["date"][0]: event_date.isoformat()},
        )
        rows = response.get("data", {}).get("rows", [])
        parsed: list[tuple[str, TournamentPlayer]] = []
        for row in rows:
            values = {cell.get("fieldId"): cell.get("value") for cell in row.get("cells", [])}
            if values.get(TOURNAMENT_FIELDS["date"][0]) != event_date.isoformat():
                continue
            row_club = str(values.get(TOURNAMENT_FIELDS["club"][0]) or "").strip()
            if club and row_club.casefold() != club.casefold():
                continue
            try:
                player = TournamentPlayer(
                    place=values[TOURNAMENT_FIELDS["place"][0]],
                    player=values[TOURNAMENT_FIELDS["player"][0]],
                    deck=values[TOURNAMENT_FIELDS["deck"][0]],
                )
            except (KeyError, ValueError) as exc:
                raise DataLensTournamentError("В строке DataLens отсутствует место, игрок или колода") from exc
            parsed.append((row_club, player))

        if not parsed:
            suffix = f' для клуба "{club}"' if club else ""
            raise DataLensTournamentError(f"В DataLens нет турнира {event_date.isoformat()}{suffix}")
        clubs = {row_club for row_club, _ in parsed}
        if len(clubs) != 1:
            raise DataLensTournamentError(
                f"На {event_date.isoformat()} найдено несколько клубов: {', '.join(sorted(clubs))}; укажите --club"
            )
        players = sorted((player for _, player in parsed), key=lambda player: player.place)
        places = [player.place for player in players]
        expected = list(range(1, len(players) + 1))
        if places != expected:
            raise DataLensTournamentError(f"Некорректные итоговые места DataLens: {places}; ожидались {expected}")
        return DataLensTournament(date=event_date, club=next(iter(clubs)), players=players)
