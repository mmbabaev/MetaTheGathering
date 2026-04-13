# Handler Architecture

Every handler file follows a strict two-layer pattern.

## Layer 1 — Pure business logic: Handler classes

```python
class FooHandler:
    def __init__(self, svc: TournamentService, user_svc: UserService) -> None:
        self.svc = svc
        self.user_svc = user_svc

    def handle_xxx(self, arg1: int, arg2: str, ...) -> HandlerResult:
        ...
```

Rules:
- Constructor receives service dependencies (e.g. `TournamentService`, `UserService`) — never Telegram objects
- Methods take **primitive values only** (int, str, bool) — never `Update`, `Message`, `User`, etc.
- Returns a `HandlerResult(text, keyboard, is_alert, needs_name)`
- Has no side effects beyond the database
- **Unit-tested directly** in `tests/` — inject real services backed by SQLite in-memory

### Handler classes

| Class | File | Dependencies |
|-------|------|-------------|
| `PlayerHandler` | `player.py` | `TournamentService`, `UserService` |
| `AdminHandler` | `admin.py` | `TournamentService`, `UserService` |
| `SettingsHandler` | `settings.py` | `UserService` |

## Layer 2 — Thin Telegram wrapper: `cmd_xxx / callback_xxx`

Lives in **`bot/telegram/`** (not in `bot/handlers/`).

```python
def _foo_handler(db) -> FooHandler:
    return FooHandler(TournamentService(db), UserService(db))

async def cmd_xxx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = _foo_handler(db).handle_xxx(user.id, ...)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
```

Rules:
- Extracts primitives from `Update` / `context`, opens a DB session, instantiates the handler, calls `handle_xxx`, sends the result
- Closes the DB session in `finally`
- **No business logic** — only Telegram I/O and `user_data` state management
- Not unit-tested (requires Telegram mocks)

## HandlerResult flags

| Flag | Meaning | Wrapper behaviour |
|------|---------|-------------------|
| `is_alert=True` | Error / warning | `query.answer(text, show_alert=True)` instead of editing the message |
| `needs_name=True` | User has no name in DB | Store `tournament_id` in `user_data[USER_DATA_PENDING_NAME]` and show the prompt |

## Multi-step text input flows

State lives in `context.user_data` with named keys (defined as constants):

| Key constant | Set by | Handled by |
|---|---|---|
| `USER_DATA_PENDING_NAME` | `callback_register` (when `result.needs_name`) | `message_text_input` |
| `USER_DATA_PENDING_CUSTOM` | `callback_custom_archetype` | `message_text_input` |
| `USER_DATA_PENDING_SETTINGS_NAME` | `callback_settings_name` | `message_text_input` |

All text input is routed through a single `message_text_input` handler that checks these keys in priority order.

## Testing pattern

Instantiate the handler class with real services; no mocks needed:

```python
@pytest.fixture
def handler(svc, user_svc):
    return PlayerHandler(svc, user_svc)

def test_foo(handler, active_tournament):
    result = handler.handle_foo(tg_id=123, ...)
    assert result.text == EXPECTED
```

## Adding a new handler

1. Write `FooHandler` class in `bot/handlers/foo.py` — pure logic, constructor-injected deps
2. Add a `_foo_handler(db)` factory and `cmd_xxx` / `callback_xxx` wrappers in `bot/telegram/foo.py`
3. Register in `main.py` (imports from `bot.telegram`)
4. Write tests in `tests/test_foo.py` using a handler fixture
5. Add any new `user_data` keys as named constants in `bot/telegram/`, document them in the table above
