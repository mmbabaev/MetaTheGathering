# Web UI: Architecture

## Контекст

Задача — добавить веб-интерфейс для записи на турниры, переиспользуя существующую инфраструктуру. Приоритет: поддерживаемость и скорость разработки.

---

## Развилка: уровень переиспользования

### Вариант A: Web routes → Services напрямую

```
bot/telegram/   web/routes/
      ↓               ↓
  bot/handlers/   services/  ← веб идёт сюда напрямую
      ↓               ↓
       services/
           ↓
    core/models + database
```

- Веб-слой вызывает `TournamentService` и другие сервисы напрямую
- `bot/handlers/` остаётся только для Telegram и не меняется
- Для новой фичи: пишешь в сервисе → отдельно подключаешь в Telegram handler и в web route

**Pros:**
- Чёткое разделение: Telegram = Telegram, Web = Web
- Никакой "universal abstraction" которая тянет в разные стороны
- Свобода в web UI — не ограничен форматом `HandlerResult`
- `bot/handlers/` не усложняется

**Cons:**
- Дублирование routing-логики (но не бизнес-логики — она в сервисах)
- Новая фича требует двух точек подключения

---

### Вариант B: Универсальные хэндлеры (один хэндлер → обе платформы)

```
bot/telegram/   web/routes/
      ↓               ↓
       bot/handlers/   ← общие для обеих платформ
           ↓
        services/
```

- `HandlerResult` расширяется: добавляется `web_actions` или аналог
- Хэндлер один раз описывает логику + какие кнопки нужны
- Каждый view-слой рендерит своё представление

**Pros:**
- Одна точка для каждой фичи
- Меньше суммарного кода при большом числе фич

**Cons:**
- `HandlerResult` сейчас заточен под Telegram (text + InlineKeyboardMarkup)
- Расширение под две платформы создаёт сложную абстракцию
- Клавиатуры Telegram (callback data, CB_* префиксы) принципиально отличаются от web actions (URL, form submit)
- При изменении фичи нужно думать об обоих контекстах одновременно
- Риск: хэндлер начинает "знать" про обе платформы — нарушение SRP

---

## Рекомендация: Вариант A

Сервисный слой (`services/`) — это и есть общая бизнес-логика. Он уже достаточно абстрактен.

`bot/handlers/` — это Telegram-специфичное форматирование. Не стоит делать его платформо-нейтральным: это усложнит его без пропорциональной выгоды.

**Правило:** новая фича → сервис → два тонких адаптера (tg handler + web route). Адаптеры дешёвые, сервисы дорогие — именно там не хочется дублирования.

---

## Стек

| Компонент | Выбор | Причина |
|-----------|-------|---------|
| Framework | FastAPI | уже async, Pydantic v2 уже есть |
| Templates | Jinja2 | серверный HTML, без build pipeline |
| JS | Минимальный vanilla JS | fetch для форм, никаких фреймворков |
| Auth | Registration token / Magic link | см. `auth.md` — независимо от Telegram |
| CSS | Tailwind CDN | один script тег, no build |

Без HTMX, без React — просто Jinja2-шаблоны + несколько строк JS для async-запросов где нужно. Легко читать и поддерживать.

---

## Структура модулей

```
web/
├── app.py              # FastAPI app instance, lifespan, middleware
├── auth.py             # verify_telegram_webapp(), get_current_user dependency
├── routes/
│   ├── __init__.py
│   ├── tournaments.py  # GET /tournaments, POST /tournaments/{id}/register
│   └── participants.py # GET /participants (для просмотра)
└── templates/
    ├── base.html
    ├── tournaments.html
    └── partials/
        └── registration_form.html  # HTMX partial
```

`web/` подключается к `main.py` через `app.mount()` или запускается отдельным портом.

---

## Scope MVP

1. Список открытых турниров
2. Запись на турнир (выбор архетипа)
3. Просмотр своей записи / отмена

Всё остальное (голосование, админка) — вторая итерация.
