# MetaGatherer — TODO

## Phase 1: MVP (current focus)

### Infrastructure (blocking)
- [ ] **`core/config.py`** — implement Pydantic Settings (DATABASE_URL, TELEGRAM_BOT_TOKEN, DEBUG)
- [ ] **`requirements.txt` / `pyproject.toml`** — declare project dependencies
- [ ] **`alembic/`** — create initial migration from existing models
- [ ] **`docker-compose.yml`** — add PostgreSQL service, bot service, env wiring

### Scheduled tournament creation
- [ ] Add `TOURNAMENT_SCHEDULE` to config (e.g. `"friday 19:00"`, timezone-aware)
- [ ] Add `TOURNAMENT_CHAT_IDS` to config — list of chat IDs to create tournaments in
- [ ] Implement scheduler via python-telegram-bot `JobQueue` — at scheduled time: close any open tournament, create new one, post announcement message to each chat
- [ ] Auto-generate tournament `title` and `slug` from the date (e.g. `"Pauper 2026-03-28"`, `"2026-03-28-pauper"`)

### Admin panel (`bot/handlers/admin.py`)
- [ ] Guard all admin handlers with `is_admin` check
- [ ] `/add_me <deck_name>` — admin registers themselves in the current tournament with a deck name
- [ ] `/add_player @username <deck_name>` — admin adds another player by Telegram username
- [ ] `/add_players` — bulk add players from a list (multiline message or CSV paste)
- [ ] `/tournament_status` — show current tournament info and participant list
- [ ] `/close` — close the current tournament

### Data seeding
- [ ] Seed initial Pauper archetype list (Burn, Affinity, Faeries, Mono-Blue Faeries, Goblins, etc.)

---

## Phase 2: Player self-registration

- [ ] `/tournaments` flow already works — validate and polish
- [ ] Guard registration: only open during `REGISTRATION` status (already enforced in service)
- [ ] **`utils/validators.py`** — validate custom archetype input (length, allowed chars)
- [ ] Fuzzy archetype matching via `ArchetypeAlias`
- [ ] Error handling: catch `ServiceError` subclasses in handlers and show user-friendly messages

---

## Phase 3: Export & Stats

- [ ] `/export` command — admin triggers CSV/Markdown export
- [ ] `/stats` — show meta breakdown for current tournament (archetype counts)
- [ ] Add JSON export format to `ExportService`

---

## Phase 4: Voting

- [ ] **`services/voting.py`** — implement voting business logic (or wire `TournamentService.cast_vote()`)
- [ ] **`bot/handlers/voting.py`** — upvote/downvote buttons, callbacks
- [ ] Add `CB_VOTE` callback prefix and vote keyboards to `bot/keyboards/__init__.py`
- [ ] Show current vote counts on participant cards during `VOTING` phase
- [ ] Admin command to edit participant archetype (resets votes)

---

## Backlog

- [ ] **`bot/middlewares/`** — auth/role middleware
- [ ] `/mystats` — player's own stats across tournaments
- [ ] **`web/api/`** — FastAPI REST endpoints (tournaments, meta, export)
- [ ] Redis caching for stats/meta queries
- [ ] Tests (pytest): service unit tests, handler integration tests
- [ ] CI pipeline (GitHub Actions)
- [ ] Sentry or similar for error tracking
