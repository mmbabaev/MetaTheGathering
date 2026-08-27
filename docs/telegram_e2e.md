# Telegram E2E tests

## In-process blocking suite

`tests/telegram_e2e/` passes synthetic Telegram `Update` objects through the real
`python-telegram-bot` `Application` and registered handlers. Bot API calls go to
`RecordingRequest`, never to Telegram's network. The transport records method names,
recipients, text, edits and inline keyboards and returns deterministic Bot API fixtures.

Run locally:

```bash
TELEGRAM_BOT_TOKEN="0000000000:dummy-not-a-real-key" \
DATABASE_URL="sqlite:///:memory:" \
python3 -m pytest tests/telegram_e2e/ -v
```

The PR workflow runs this directory as the separate blocking check
`Telegram integration E2E`. The ordinary test job excludes it to avoid running the same
flow twice.

### Harness rules

- Use obviously fake bot tokens and isolated SQLite/PostgreSQL fixtures only.
- Assert every recorded `chat_id`; a test must fail on an unexpected recipient.
- Find callback data through the visible button text instead of hard-coding database IDs.
- Disable `post_init` and the scheduler unless the scenario explicitly tests them.
- Add an explicit fixture response before exercising a new Bot API method. Unknown methods
  fail rather than silently succeeding.
- Never configure a production/debug bot token, production DB or club chat in this suite.

## Real Telegram smoke

The real post-deploy smoke described in
[#270](https://github.com/mmbabaev/MetaTheGathering/issues/270) is not implemented yet.
It will require a separate Telegram test account and debug-only secrets. Do not run a
second polling process with an existing bot token.
