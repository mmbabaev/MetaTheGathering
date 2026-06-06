# DataLens — чтение личной статистики игроков

Каноническая точка по работе с дашбордом Yandex DataLens «Личная статистика»
(dashId `6dr39r9a9l9mt`). Дашборд публичный — запросы идут **анонимно, без cookie**.

## Где код

- **`services/datalens.py`** — рабочий сервис. Используй его, а не сырые запросы.
  - `DataLensService` — `player_decks()`, `winrate_vs_opponents()`,
    `winrate_vs_opponent_decks()`, `player_report(player, period, charts=...)`,
    `scout_opponent(player, opponent, ...)`.
  - `DataLensClient` — тонкий HTTP-клиент (`session` инжектируется → можно прокси/мок).
  - `Period` — `all_time()`, `since(date)`, `last_months(n)`, `last_days(n)`.
  - `StatRow(name, matches, winrate)`, `PlayerReport`, `OpponentScouting` — pydantic.
- **`tests/test_datalens_service.py`** — юнит-тесты с замоканным API (паттерн `MagicMock`).
- **`scripts/datalens_parser/verify_service.py`** — ручная проверка, кладёт JSON в `~/Downloads`:
  ```bash
  python3 scripts/datalens_parser/verify_service.py 'Бабаев Михаил' --months 2
  python3 scripts/datalens_parser/verify_service.py 'Бабаев Михаил' --scout 'Ашаров Вадим'
  ```
- `datalens_parser.py`, `datalens_player_stats.py` — старые одноразовые скрипты (legacy,
  оставлены как справка); `*_response.json` — примеры ответов API.

## Как устроен API

Эндпоинт: `POST https://datalens.yandex/charts/api/run`. Каждый виджет дашборда —
это «чарт» со своим `chartId`. Значения селекторов (игрок, период, турнир) кладутся
в `params` под guid-именами полей датасета `s1jvqelyx5i6f`.

Чарты дашборда (получены через `getPublicEntry`, см. ниже):

| chartId | виджет | сервис |
|---|---|---|
| `jsaobu3lpeos6` | Декчойс (колоды игрока) | `Chart.DECKS` |
| `z8rami53rgu0m` | Оппонент и винрейт против него | `Chart.OPPONENTS` |
| `en6q8x8cdhs61` | Винрейт против дек оппонентов | `Chart.OPPONENT_DECKS` |
| `47cz6kdjt7cer` | Дейлики | — (не используется) |
| `evx1vgo8fpg61` | Кол-во матчей и винрейт | — (не используется) |

Все три используемых чарта отдают единообразную таблицу `[имя, матчей, winrate]` —
парсер `_parse_row` берёт колонки **позиционно** (не по guid метрик).

Параметры запроса (`params`):
- `igrok_4vy1` и `uchastnik_0zyi` — имя игрока «Фамилия Имя» (передаём в оба);
- `data_v9da` — интервал дат (см. ниже);
- `klub_77wt` — фильтр по турниру, пусто `""` = все.

### Фильтр периода (важная гоча)

В публичном режиме надёжно работает только «абсолютная дата → сейчас»:
```
__interval_2025-01-01T00:00:00.000Z___relative_-0d   (ТРИ подчёркивания перед relative)
```
НЕ работает: два абсолютных значения → HTTP **427**; голый `-2M` → не фильтрует.
Поэтому `Period.last_months(n)` вычисляет абсолютное начало `today - n мес`.

### Как заново найти chartId / поля (если дашборд изменят)

```python
import requests
H = {"Content-Type":"application/json","Accept":"application/json","Origin":"https://datalens.yandex",
     "Referer":"https://datalens.yandex/6dr39r9a9l9mt","x-dl-component":"ui","x-dl-display-mode":"basic"}
d = requests.post("https://datalens.yandex/gateway/root/us/getPublicEntry",
                  json={"entryId":"6dr39r9a9l9mt"}, headers=H).json()
for tab in d["data"]["tabs"]:
    for it in tab.get("items", []):
        for w in it.get("data", {}).get("tabs", []):
            print(w.get("title"), w.get("chartId"))
```
Внимание: `getEntry` для публичного дашборда даёт `400 invalid public request` —
нужен именно `getPublicEntry`.

Список всех игроков (~610 «Фамилия Имя») лежит в ответе чарта-селектора в
`uiScheme[0]["content"]` — пригодится для маппинга telegram-юзера на имя в дашборде.

## Прод

До `datalens.yandex` с Яндекс-VM ходим **напрямую** — это Яндекс, прокси (как для
Telegram) не нужен.

## Обобщённый рецепт для других дашбордов

Лежит в долговременной памяти: `~/Develop/ai/web_scraping/yandex-datalens-public-dashboard.md`.
