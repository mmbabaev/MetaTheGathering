# datalens_parser

Скрипты для получения статистики игроков из Yandex DataLens (дашборд Pauper-лиги).

## Файлы

- **`datalens_parser.py`** — парсер ответа DataLens. Класс `PlayerChoicesResponse` принимает `dict` ответа и возвращает список `DeckStats(name, matches, winrate)` через метод `.decks()`.
- **`datalens_player_stats.py`** — CLI-скрипт. Принимает имя игрока, делает запрос к DataLens, выводит таблицу колод.

## Запуск

```bash
# из папки scripts/
python3 datalens_parser/datalens_player_stats.py 'Фамилия Имя'
```

## API

Запросы идут к `https://datalens.yandex/charts/api/run`, chart id `jsaobu3lpeos6`. Авторизация не требуется.

Список всех игроков лежит в ответе селектора по пути `uiScheme[0]["content"]` (пример: `players_list_response.json`).

## Примеры ответов

- `datalens_get_player_response_example.json` — полный ответ для Бабаева Михаила
- `datalens_vasiliev_response.json` — ответ для Васильева Сергея
- `players_list_response.json` — ответ селектора со списком всех игроков
