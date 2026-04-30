# Web UI: Implementation Plan

## Scope

Веб-интерфейс для игроков без Telegram. Повторяет основной пользовательский функционал бота:

1. Авторизация (email + magic link)
2. Запись на турнир
3. Просмотр турнира
4. Настройки имени
5. Запись оппонента

---

## Изменения в data model

`tg_id NOT NULL` **не трогаем**. В системе уже есть паттерн placeholder-пользователей с отрицательным `tg_id` (`get_or_create_placeholder`, `get_or_create_by_name`). Веб-пользователи используют тот же механизм.

### Изменения в `User` (только additive)

```python
email        = Column(String(255), unique=True, nullable=True, index=True)  # новое
display_name = Column(String(255), nullable=True)                           # новое
```

`tg_id` остаётся `NOT NULL`. Веб-пользователь создаётся с отрицательным `tg_id` (то же что плейсхолдеры для оппонентов). Email отличает веб-юзеров от плейсхолдеров по имени.

### Новая таблица `WebAuthToken`

```python
class WebAuthToken(Base):
    __tablename__ = "web_auth_tokens"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hex
    expires_at = Column(DateTime, nullable=False)
    used_at    = Column(DateTime, nullable=True)  # NULL = не использован
```

Сессия — `user_id` в подписанном httponly cookie через `itsdangerous.TimestampSigner`, TTL 90 дней.

### Миграция

```
alembic revision --autogenerate -m "web_user_support"
```

Что изменится (только additive, существующий код не ломается):
- `users.email`: новая nullable колонка
- `users.display_name`: новая nullable колонка
- Новая таблица `web_auth_tokens`

### Слияние аккаунтов (Web → Telegram)

Расширяем существующий `merge_placeholder_by_name` или добавляем `merge_web_user_with_tg(web_user_id, real_tg_id)`:
- Переносим `Participant`, `UserDeckHistory` на реального tg-пользователя
- Копируем `email` и `display_name` на tg-пользователя
- Удаляем веб-плейсхолдер
- Инвалидируем веб-сессию (нужна повторная авторизация через Telegram или остаётся)

---

## Структура модулей

```
web/
├── app.py                  # FastAPI instance, lifespan, static files, template engine
├── auth.py                 # deps: get_current_user; magic link logic
├── email.py                # send_magic_link() — обёртка над SMTP
├── routes/
│   ├── __init__.py
│   ├── auth.py             # GET /login, POST /login, GET /auth/verify
│   ├── tournaments.py      # GET /, GET /t/{id}, POST /t/{id}/register
│   ├── me.py               # GET /me, DELETE /me/registrations/{id}
│   ├── opponent.py         # POST /t/{id}/register-opponent
│   └── settings.py         # GET /settings, POST /settings
└── templates/
    ├── base.html
    ├── login.html
    ├── tournaments.html     # список
    ├── tournament.html      # детальная + форма записи
    ├── me.html              # мои записи
    └── settings.html
```

---

## Роуты

| Method | Path | Описание |
|--------|------|----------|
| GET | `/login` | Форма ввода email |
| POST | `/login` | Отправить magic link |
| GET | `/auth/verify` | Верифицировать токен из письма, создать сессию |
| GET | `/logout` | Удалить сессию |
| GET | `/` | Список открытых турниров |
| GET | `/t/{id}` | Детали турнира, список участников, форма записи |
| POST | `/t/{id}/register` | Записаться на турнир |
| POST | `/t/{id}/register-opponent` | Записать оппонента |
| GET | `/me` | Мои записи на турниры |
| DELETE | `/me/registrations/{id}` | Отменить запись |
| GET | `/settings` | Форма настроек имени |
| POST | `/settings` | Сохранить имя |

---

## Auth flow (email + magic link)

```
POST /login {email}
  → найти/создать User(email=...) в БД
  → сгенерировать token = secrets.token_urlsafe(32)
  → сохранить WebAuthToken(user_id, sha256(token), expires_at=now+15min)
  → отправить письмо: "Войти → /auth/verify?token=TOKEN"
  → показать страницу "Проверьте почту"

GET /auth/verify?token=TOKEN
  → найти WebAuthToken где token_hash = sha256(TOKEN) и expires_at > now и used_at IS NULL
  → пометить used_at = now
  → создать сессию: подписанный cookie с user_id (itsdangerous.TimestampSigner, TTL 30 дней)
  → redirect /
```

Зависимость в роутах:
```python
async def get_current_user(request: Request, db: Session) -> User:
    user_id = verify_session_cookie(request)
    if not user_id:
        raise HTTPException(303, headers={"Location": "/login"})
    return db.get(User, user_id)
```

---

## Запись на турнир

Использует `TournamentService` напрямую (не через `bot/handlers/`):

```python
# web/routes/tournaments.py
@router.post("/t/{tournament_id}/register")
async def register(tournament_id: int, archetype_id: int, user: User = Depends(get_current_user)):
    service = TournamentService(db)
    service.register_participant(
        tournament_id=tournament_id,
        user_id=user.id,
        archetype_id=archetype_id,
    )
    return RedirectResponse(f"/t/{tournament_id}", status_code=303)
```

Форма показывает список архетипов из БД. Кастомный архетип — отдельное текстовое поле.

---

## Запись оппонента

Оппонент может не иметь аккаунта. Варианты:
1. **Создать User(email=None, tg_id=None, first_name=имя)** — "анонимный" юзер, созданный регистратором
2. Не создавать User — просто хранить имя оппонента в Participant как строку

Вариант 1 чище (не ломает FK), но создаёт "мусорных" пользователей без email и tg_id.

**Решение:** добавить поле `guest_name: str | None` в `Participant` для случаев когда оппонент не в системе. `user_id` остаётся nullable-вторым вариантом. Либо просто создавать User с `first_name` и без tg_id/email — зависит от того нужна ли им возможность потом войти.

> Этот момент требует уточнения у пользователя: оппонент должен потом иметь возможность войти на сайт и увидеть свою запись?

---

## Настройки имени

Поле `User.display_name` (добавить в модель):
- У Telegram-пользователей — берётся из `first_name` если `display_name` не задан
- У веб-пользователей — обязательно заполняется при первом входе (редирект на `/settings` если пусто)

---

## Конфигурация

Новые env-переменные в `.env`:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=bot@example.com
SMTP_PASSWORD=...
SMTP_FROM=MetaGatherer <bot@example.com>

WEB_SECRET_KEY=<random 32 bytes hex>  # для подписи cookie
WEB_BASE_URL=https://metagatherer.ru  # для ссылок в письмах

WEB_PORT=8080  # FastAPI порт (бот на другом)
```

---

## Фазы реализации

### Фаза 1: Фундамент (2-3 часа)
- [ ] Миграция: `tg_id` nullable, `email`, `display_name` в `User`; таблица `WebAuthToken`
- [ ] `web/app.py`: FastAPI + Jinja2 + static
- [ ] `web/email.py`: `send_magic_link()` через SMTP
- [ ] `web/auth.py`: генерация/верификация токена, сессия через cookie
- [ ] Роуты `/login`, `/auth/verify`, `/logout`
- [ ] Базовый шаблон (`base.html`, `login.html`)

### Фаза 2: Турниры (2-3 часа)
- [ ] `GET /` — список турниров со статусом
- [ ] `GET /t/{id}` — детали: описание, список участников, форма записи
- [ ] `POST /t/{id}/register` — запись с выбором архетипа
- [ ] Шаблоны: `tournaments.html`, `tournament.html`

### Фаза 3: Личный кабинет (1-2 часа)
- [ ] `GET /me` — мои записи
- [ ] `DELETE /me/registrations/{id}` — отмена
- [ ] `GET/POST /settings` — имя
- [ ] Редирект на `/settings` при пустом `display_name`

### Фаза 4: Запись оппонента (1-2 часа)
- [ ] Уточнить: оппонент должен потом войти? → выбрать стратегию
- [ ] `POST /t/{id}/register-opponent`
- [ ] Форма на странице турнира

### Фаза 5: Интеграция (1 час)
- [ ] Подключить `web/app.py` к `main.py` (отдельный порт или mount)
- [ ] Обновить `core/config.py` с новыми env-переменными
- [ ] Тесты для web-роутов (FastAPI TestClient)

---

## Открытые вопросы

1. **Оппонент без аккаунта** — может ли он потом войти и увидеть свою запись?
2. **Домен** — где будет хоститься веб? Отдельный сервер или тот же?
3. **Связка Telegram ↔ Web** — если игрок есть в боте и потом регистрируется через веб с тем же именем — мержить аккаунты?
