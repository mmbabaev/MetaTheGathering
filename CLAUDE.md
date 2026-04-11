# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**MetaGatherer** is a Telegram bot for collecting Magic: The Gathering Pauper tournament metagame data. Players self-register with deck archetypes; the community validates archetypes via voting. Admins export aggregated meta in CSV/Markdown.

## Running

```bash
# Run bot (polling mode)
python main.py
```

Requires `TELEGRAM_BOT_TOKEN` and `DATABASE_URL` in `.env`. PostgreSQL must be running. `core/config.py` is not yet implemented — this is the first thing to set up.

## Architecture

### Layered structure

```
main.py  →  bot/handlers/  →  services/  →  core/models + database
```

- **`main.py`** — wires Telegram handlers and starts polling
- **`bot/handlers/`** — async Telegram callbacks; each handler opens a `SessionLocal()`, instantiates `TournamentService(db)`, calls service methods, then closes the session in `finally`
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

Uses `context.user_data[USER_DATA_PENDING_CUSTOM]` to store `tournament_id` between the callback and the subsequent text message. Key: `"pending_custom_archetype_tournament_id"` in `bot/handlers/player.py`.

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
- `handle_xxx(db, ...primitives) → HandlerResult` — pure business logic, tested directly (no Telegram mocks)
- `cmd_xxx / callback_xxx` — thin Telegram wrappers that call `handle_xxx` and send the result

`HandlerResult` is defined in `bot/handlers/base.py` (`text`, `keyboard`, `is_alert`).

**Current status (96 tests, all passing, ~81% coverage):**

| File | Coverage | Notes |
|------|----------|-------|
| `services/tournament.py` | 88% | Main business logic |
| `services/utils.py` | 92% | |
| `core/models.py`, `schemas.py`, `config.py` | 100% | |
| `bot/keyboards/__init__.py`, `bot/messages/__init__.py`, `bot/handlers/base.py` | 100% | |
| `utils/seed.py` | 85% | |
| `bot/handlers/admin.py` | 64% | `handle_xxx` covered, `cmd_xxx` wrappers not |
| `bot/handlers/player.py` | 41% | `handle_xxx` covered, `callback_xxx` wrappers not |
| `bot/scheduler.py` | 43% | `_create_tournaments_for_schedule` not covered |
| `bot/handlers/common.py` | 0% | Trivial /start and /help |

Tests use **SQLite in-memory** — no real PostgreSQL needed. See `docs/test_plan.md` for the full plan.

## What's not implemented yet

See `TODO.md`. The most notable stubs:
- `bot/handlers/voting.py` — empty
- `services/voting.py` — empty (voting logic lives in `TournamentService.cast_vote()`)
- `utils/formatters.py`, `utils/validators.py` — empty stubs
