# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**MetaGatherer** is a Telegram bot for collecting Magic: The Gathering Pauper tournament metagame data. Players self-register with deck archetypes; the community validates archetypes via voting. Admins export aggregated meta in CSV/Markdown.

## ⚠️ Notification safety (hard rules)

> **NEVER send mass / broadcast DMs.** Real users receive every message the bot sends them — a wrong fan-out spams real people and is not reversible.
>
> - **Debug / test tooling must message ONLY the user who triggered it** — filter to `tg_id == requester` and send exclusively to that chat_id. Never deliver other players' notifications to the requester, and never DM other players from a debug action.
> - Any new code path that calls `bot.send_message` in a loop over multiple users requires explicit confirmation from the user before it ships.
> - Production notifications must respect the `notify_allowed_ids` gate and only target their genuine intended recipient.

## Alembic migrations

> **NEVER reuse a placeholder revision id** like `a1b2c3d4e5f6` — many already exist and collisions cause "multiple/zero heads" failures (the bot won't start; CI breaks). Generate a fresh id: `python3 -c "import uuid; print(uuid.uuid4().hex[:12])"`, set `down_revision` to the current head, and verify with `DATABASE_URL="sqlite:///:memory:" python3 -m alembic heads` (must be exactly one). `tests/test_migrations.py` enforces this.

## Running

> **WARNING:** Never run `python main.py` or `./server.sh` locally with the production token (`TELEGRAM_BOT_TOKEN` from `.env`). A local instance polling the same token causes continuous `Conflict: terminated by other getUpdates request` errors on the production server, making the bot intermittently unresponsive. This is hard to diagnose. Use a separate test bot token for local development.
>
> **Deployment must go through GitHub Actions** (push to `main` → prod deploy, open PR → debug deploy). Manual `deploy_bot.sh` is a last resort only.

```bash
# Run bot (polling mode)
python main.py

# Preferred: use server.sh for background process management
./server.sh           # restart (stop old + start new) — default
./server.sh start     # start if not running
./server.sh stop      # stop
./server.sh status    # show PID and last 20 log lines
./server.sh logs      # tail -f server.log
```

`server.sh` uses a PID file (`.server.pid`) and logs to `server.log` (both gitignored). Use `./server.sh restart` to redeploy after code changes.

Requires `TELEGRAM_BOT_TOKEN` and `DATABASE_URL` in `.env`. PostgreSQL must be running. `core/config.py` is not yet implemented — this is the first thing to set up.

## Debug CLI

`cli.py` — локальный инструмент для работы с debug-базой и E2E-тестирования. Переиспользует `services/` напрямую. Подробнее: [`docs/cli.md`](docs/cli.md).

```bash
python3 cli.py tournament list
python3 cli.py tournament delete-last -y
python3 cli.py tournament create "Pauper Friday #42"
python3 cli.py tournament import https://aetherhub.com/Tourney/RoundTourney/99291
python3 cli.py tournament export-excel -o /tmp/results.xlsx

python3 -m pytest tests/e2e/ -v   # регрессионные E2E тесты
```

## Architecture

### Layered structure

```
main.py  →  bot/telegram/  →  bot/handlers/  →  services/  →  core/models + database
```

- **`main.py`** — wires Telegram handlers and starts polling; imports from `bot/telegram/`
- **`bot/telegram/`** — thin async Telegram wrappers (`cmd_xxx`, `callback_xxx`); extract primitives from `Update`/`context`, open a `SessionLocal()`, call the corresponding `handle_xxx`, send the result. Not unit-tested.
- **`bot/handlers/`** — pure business logic (`handle_xxx` functions); take only primitives + `Session`, return `HandlerResult`. No Telegram imports. 100% unit-testable.
- **`bot/keyboards/`** — callback prefix constants (`CB_*`) and inline keyboard builders; callback data format is `PREFIX:arg1:arg2`
- **`bot/messages/`** — Russian-language string constants and `format_*` helpers
- **`services/tournament.py`** — the primary service class `TournamentService`; handles tournament lifecycle, participant registration, voting, and meta aggregation
- **`services/errors.py`** — re-exports the exception hierarchy from `services_errors.py`; handlers catch these by type
- **`core/models.py`** — SQLAlchemy ORM models (7 tables)
- **`core/schemas.py`** — Pydantic v2 read/create schemas used as service return types (all use `model_validate()`)
- **`core/database.py`** — `SessionLocal` (scoped session factory) and `Base`

### Tournament state machine

`REGISTRATION → ONGOING → VOTING → CLOSED`

- `register_participant()` only allowed in `REGISTRATION`
- `cast_vote()` only allowed in `VOTING`
- `ensure_tournament_status()` in `services/utils.py` raises `TournamentInvalidState` on mismatch
- One active (non-CLOSED) tournament per `chat_id`

### Voting rules

Defined in `services/tournament.py`:
- `CONFIRM_THRESHOLD = 3`: `upvotes - downvotes >= 3` → `participant.confirmed = True`
- `REJECT_THRESHOLD = 3`: `downvotes - upvotes >= 3` → `participant.confirmed = False`
- `CHANGE_VOTE_COOLDOWN = 30s` between vote changes per voter
- Self-votes raise `SelfVoteNotAllowed`
- Editing a participant's archetype resets all votes (`set_participant_archetype(reset_votes=True)`)

### Custom archetype flow

Uses `context.user_data[USER_DATA_PENDING_CUSTOM]` to store `tournament_id` between the callback and the subsequent text message. Key: `"pending_custom_archetype_tournament_id"` in `bot/telegram/player.py`.

## Tests

```bash
# Run all tests
python3 -m pytest tests/

# Run with coverage report
python3 -m pytest tests/ --cov=. --cov-report=term-missing --ignore=.venv

# Run a single test file
python3 -m pytest tests/test_tournament_service.py -v
```

**Handler testing pattern** — handlers are split into two layers:
- `handle_xxx(db, ...primitives) → HandlerResult` in `bot/handlers/` — pure business logic, tested directly (no Telegram mocks)
- `cmd_xxx / callback_xxx` in `bot/telegram/` — thin Telegram wrappers that call `handle_xxx` and send the result; not unit-tested

`HandlerResult` is defined in `bot/handlers/base.py` (`text`, `keyboard`, `is_alert`, `needs_name`).

**Current status (181 tests, all passing, ~84% coverage):**

| File | Coverage | Notes |
|------|----------|-------|
| `services/tournament.py` | 100% | Main business logic |
| `services/utils.py` | 100% | |
| `core/models.py`, `schemas.py` | 100% | |
| `core/config.py` | 90% | |
| `bot/keyboards/__init__.py`, `bot/messages/__init__.py`, `bot/handlers/base.py` | 100% | |
| `bot/handlers/admin.py` | 99% | Pure logic only — fully covered |
| `bot/handlers/player.py` | 100% | Pure logic only — fully covered |
| `bot/handlers/settings.py` | 100% | Pure logic only — fully covered |
| `bot/scheduler.py` | 100% | |
| `utils/seed.py` | 85% | |
| `bot/telegram/` | 0% | Telegram wrappers — not unit-tested by design |
| `main.py` | 0% | Entry point wiring only |

Tests use **SQLite in-memory** — no real PostgreSQL needed. See `docs/test_plan.md` for the full plan.

## What's not implemented yet

See `TODO.md`. The most notable stubs:
- `bot/handlers/voting.py` — empty
- `services/voting.py` — empty (voting logic lives in `TournamentService.cast_vote()`)
- `utils/formatters.py`, `utils/validators.py` — empty stubs
