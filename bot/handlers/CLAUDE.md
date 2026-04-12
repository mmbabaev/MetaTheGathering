# Handler Architecture

Every handler file follows a strict two-layer pattern.

## Layer 1 — Pure business logic: `handle_xxx`

```python
def handle_xxx(db: Session, arg1: int, arg2: str, ...) -> HandlerResult:
    ...
```

Rules:
- Takes a SQLAlchemy `Session` and **primitive values only** (int, str, bool) — never Telegram objects (`Update`, `Message`, `User`, etc.)
- Returns a `HandlerResult(text, keyboard, is_alert, needs_name)`
- Has no side effects beyond the database
- **Unit-tested directly** in `tests/` — no Telegram mocks needed

## Layer 2 — Thin Telegram wrapper: `cmd_xxx / callback_xxx`

Lives in **`bot/telegram/`** (not in `bot/handlers/`).

```python
async def cmd_xxx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    db = SessionLocal()
    try:
        result = handle_xxx(db, user.id, ...)
        await msg.reply_text(result.text, reply_markup=result.keyboard)
    finally:
        db.close()
```

Rules:
- Extracts primitives from `Update` / `context`, opens a DB session, calls `handle_xxx`, sends the result
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

All text input is routed through a single `message_text_input` handler that checks these keys in priority order. Each branch calls the corresponding pure `handle_xxx` function.

## Adding a new handler

1. Write `handle_xxx(db, ...primitives) -> HandlerResult` in `bot/handlers/` — pure logic, tested
2. Write `cmd_xxx` or `callback_xxx` in `bot/telegram/` — thin wrapper, not tested
3. Register in `main.py` (imports from `bot.telegram`)
4. Add any new `user_data` keys as named constants in `bot/telegram/`, document them in the table above
